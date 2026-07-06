# Runbook: AD-Service-Bind auf Kerberos/GSSAPI umstellen (keytab)

Stellt den AD-Bind von `SIMPLE` (Bind-DN + Passwort) auf **GSSAPI/Kerberos**
um. Danach existiert **kein Bind-Passwort** mehr in DB, `.env` oder Logs — AD
verwaltet das Konto, der Container authentifiziert sich per Keytab.

Siehe [ADR 0007](../adr/0007-ad-gssapi-service-bind.md). Gilt für **alle**
AD-Operationen (Sync, Passwort-Reset, Provisioning).

**Voraussetzung:** Docker-Host ist AD-integriert (SSSD/realmd, domain-joined),
KDC erreichbar, Zeit per NTP synchron.

---

## 1. Service-Konto + Keytab in AD anlegen (`msktutil`, auf dem Host)

```bash
sudo apt-get install -y msktutil krb5-user

# Erzeugt ein Computer-/Service-Konto und schreibt dessen Keytab. --use-service-account
# hält es als normales Konto (kein Host-Prinzipal). Passwort wird zufällig gesetzt
# und ist nirgends sichtbar; --auto-update rotiert es später.
sudo msktutil create \
  --use-service-account \
  --account-name svc-magister \
  --service ldap \
  --keytab /etc/magister/krb5.keytab \
  --user-creds-only \
  --computer-name SVC-MAGISTER

sudo chmod 600 /etc/magister/krb5.keytab
klist -k /etc/magister/krb5.keytab      # Kontrolle: Principal ist drin
```

> Der Principal hat die Form `svc-magister@REALM` (bzw. `ldap/…`). Merke ihn dir
> für Schritt 4 (`KRB5_CLIENT_KTNAME` reicht i.d.R. — kein expliziter Principal nötig).

## 2. Rechte des Kontos in AD

Dem Konto in den Ziel-OUs delegieren (wie beim SIMPLE-Konto):
**Benutzer anlegen** und **Passwort zurücksetzen** (für das Provisioning), plus
Lesen für den Sync. Ohne diese Rechte schlägt Anlegen/Reset zeilenweise fehl.

## 3. Keytab + krb5.conf in den Container mounten

In `deploy/compose/docker-compose.yml` (bzw. als Override) beim `magister-api`:

```yaml
    volumes:
      - /etc/krb5.conf:/etc/krb5.conf:ro
      - /etc/magister/krb5.keytab:/etc/magister/krb5.keytab:ro
    environment:
      MAGISTER_AD_BIND_MODE: gssapi
      KRB5_CLIENT_KTNAME: /etc/magister/krb5.keytab
      # optional, falls ein Ticket-Cache gewünscht ist:
      # KRB5CCNAME: /tmp/krb5cc_magister
```

`ldap3`/MIT-Kerberos holt die Credentials automatisch aus dem **Client-Keytab**
(`KRB5_CLIENT_KTNAME`) — kein manuelles `kinit` nötig. (Falls eure krb5-Version
das nicht tut: im Entrypoint `kinit -k -t /etc/magister/krb5.keytab <principal>`
vor `uvicorn` und per `k5start`/cron erneuern.)

## 4. Bind-Passwort entfernen

- In `.env`: `MAGISTER_AD_BIND_PASSWORD` und `MAGISTER_AD_BIND_DN` leeren/löschen.
- In der Admin-UI (falls dort gesetzt): das Bind-Passwort leeren — im
  `gssapi`-Modus wird es nicht mehr gelesen.

## 5. Neu bauen & starten

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml -f docker-compose.selfsigned.yml -f docker-compose.build.yml build magister-api
docker compose -f docker-compose.yml -f docker-compose.selfsigned.yml up -d magister-api
```

## 6. Verifizieren

```bash
# im Container prüfen, dass das Ticket aus dem Keytab kommt:
docker compose exec magister-api klist -k /etc/magister/krb5.keytab

# funktionaler Test (Admin-Session): muss ok liefern
curl -sk -X POST -H "Cookie: session=…" https://<host>/api/admin/ad-test | jq .
```

Danach einmal einen Sync bzw. einen Provisioning-Testlauf machen und die Logs
auf `ldap_bind_failed` prüfen.

## Rotation

`msktutil` rotiert das Konto-Passwort und aktualisiert den Keytab:

```bash
# per cron auf dem Host, z.B. wöchentlich:
sudo msktutil update --auto-update --keytab /etc/magister/krb5.keytab --computer-name SVC-MAGISTER
```

Da der Keytab read-only in den Container gemountet ist, zieht die App die neue
Version automatisch (ggf. Container-Neustart, falls ein Ticket-Cache gecacht war).

## Zurück auf SIMPLE

`MAGISTER_AD_BIND_MODE` entfernen (Default `simple`), Bind-DN/Passwort wieder
setzen, neu starten. Kein Datenbank-/Migrations-Eingriff nötig.
