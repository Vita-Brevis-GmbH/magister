# Runbook: AD-Service-Bind komplett auf Keytab/GSSAPI umstellen

Stellt den AD-Bind von `SIMPLE` (Bind-DN + Passwort) auf **Kerberos/GSSAPI** mit
**Keytab** um. Danach existiert **kein Bind-Passwort** mehr in DB, `.env` oder
Logs — AD verwaltet das Konto, der Container authentifiziert sich per Keytab.
Gilt für **alle** AD-Operationen (Sync, Passwort-Reset, Provisioning).

Siehe [ADR 0007](../adr/0007-ad-gssapi-service-bind.md).

> **Ist das „nur ein Haken"?** Nein. Der Haken in der Admin-UI ist der **letzte**
> Schritt. Die eigentliche Arbeit ist: Keytab erzeugen (Schritt 2), Rechte
> delegieren (3), Keytab **mit korrektem Dateirecht** in den Container mounten
> (5). Plane ~30–60 Minuten inkl. Test ein. Alles andere lässt sich jederzeit
> per Haken/Env zurückdrehen (Schritt 9).

---

## 0. Voraussetzungen prüfen (auf dem Docker-Host)

Der Host ist bereits AD-integriert (SSSD/realm). Trotzdem einmal durchgehen —
90 % der GSSAPI-Fehler kommen von genau diesen Punkten:

```bash
realm list                         # Host ist domain-joined?
klist -k /etc/krb5.keytab 2>/dev/null | head   # Host-Keytab existiert (Join ok)
timedatectl                        # NTP synchron? (Kerberos toleriert nur ~5 Min Skew)
getent hosts dc1.schule.local      # DC per FQDN auflösbar (forward)
dig +short -x <DC-IP>              # UND reverse (PTR) — GSSAPI braucht beides
nc -vz dc1.schule.local 636        # LDAPS erreichbar
```

**Wichtig:** Für GSSAPI müssen die Domain-Controller in `MAGISTER_AD_DCS` als
**FQDN** stehen (nicht als IP) — der Kerberos-Service-Ticket-Name ist
`ldap/<dc-fqdn>`. Reverse-DNS (PTR) der DCs muss stimmen.

---

## 1. Zeit & Realm

```bash
sudo timedatectl set-ntp true      # falls nicht schon aktiv
```
Der Realm ist der Domänenname in GROSSBUCHSTABEN (z. B. `SCHULE.LOCAL`).

---

## 2. Service-Konto + Keytab in AD anlegen (`msktutil`)

```bash
sudo apt-get install -y msktutil krb5-user

sudo msktutil create \
  --use-service-account \
  --account-name svc-magister \
  --service ldap \
  --keytab /etc/magister/krb5.keytab \
  --user-creds-only \
  --computer-name SVC-MAGISTER \
  --description "Magister LDAP service bind"
```

Flag-Erklärung:
- `--use-service-account` → normales Dienstkonto (kein Host/Computer-Prinzipal).
- `--account-name` → der sAMAccountName des Dienstkontos in AD.
- `--service ldap` → registriert den SPN, den der Client anfordert (`ldap/…`).
- `--keytab` → Zieldatei; enthält die Kerberos-Keys, **kein** Klartext-Passwort.
- `--user-creds-only` → nutzt deine (Admin-)Anmeldung, um das Konto anzulegen.

Kontrolle:
```bash
sudo klist -k /etc/magister/krb5.keytab      # zeigt den/die Prinzipale + KVNO
```
Merke dir den Prinzipalnamen, z. B. `svc-magister@SCHULE.LOCAL`.

---

## 3. AD-Rechte des Kontos delegieren

Dem Konto `svc-magister` in **jeder** Ziel-OU (Schüler Zyklus 3, übrige,
Lehrer) delegieren:
- **Benutzer erstellen/löschen** (fürs Provisioning),
- **Passwort zurücksetzen** (`Reset Password`),
- Lesen (für den Sync).

Per GUI: *Active Directory-Benutzer und -Computer* → Rechtsklick auf die OU →
*Objektverwaltung zuweisen…* → Konto `svc-magister` → „Erstellt … Benutzerkonten
/ setzt Kennwörter zurück". Oder per `dsacls`:
```
dsacls "OU=Schueler,OU=Volksschule,DC=schule,DC=local" /I:T ^
  /G "SCHULE\svc-magister:CCDC;user" ^
  "SCHULE\svc-magister:CA;Reset Password;user"
```
Ohne diese Rechte binden geht, aber Anlegen/Reset scheitert **zeilenweise**
(sichtbar im Import-Ergebnis, kein Totalabbruch).

---

## 4. DC-FQDNs setzen

In der `.env` (bzw. Admin-UI) `MAGISTER_AD_DCS` auf **FQDNs** setzen:
```dotenv
MAGISTER_AD_DCS=dc1.schule.local,dc2.schule.local
```

---

## 5. Keytab + krb5.conf in den Container mounten  ⚠ häufigste Fehlerquelle

Der API-Container läuft als **uid 1000** (`magister`). Der gemountete Keytab
muss für **diese UID lesbar** sein — sonst „Permission denied / no creds".

```bash
# Keytab uid 1000 lesbar machen (der Container-User) und eng halten:
sudo chown 1000:1000 /etc/magister/krb5.keytab
sudo chmod 600 /etc/magister/krb5.keytab
```

In `deploy/compose/docker-compose.yml` (oder als eigenes Override) beim
`magister-api`-Service:
```yaml
    volumes:
      - /etc/krb5.conf:/etc/krb5.conf:ro
      - /etc/magister/krb5.keytab:/etc/magister/krb5.keytab:ro
    environment:
      KRB5_CLIENT_KTNAME: /etc/magister/krb5.keytab
      KRB5CCNAME: /tmp/krb5cc_magister      # beschreibbarer Cache-Pfad (uid 1000)
```

MIT-Kerberos holt die Credentials automatisch aus dem **Client-Keytab**
(`KRB5_CLIENT_KTNAME`) — normalerweise kein manuelles `kinit` nötig.
Falls eure krb5-Version das nicht tut, im Entrypoint vor `uvicorn`:
`kinit -k -t /etc/magister/krb5.keytab svc-magister@SCHULE.LOCAL` und per
`k5start`/cron erneuern.

---

## 6. Modus aktivieren + Passwort entfernen

Zwei Wege — **einer** genügt:
- **UI (empfohlen):** Admin → Einstellungen → Häkchen **„AD-Bind über
  Kerberos/GSSAPI (ohne Passwort)"** setzen, speichern. Bind-DN/Passwort-Felder
  werden deaktiviert.
- **Env:** `MAGISTER_AD_BIND_MODE=gssapi` in der `.env`.

Danach das alte Secret entfernen:
- `.env`: `MAGISTER_AD_BIND_PASSWORD=` und `MAGISTER_AD_BIND_DN=` leeren.
- In der UI war das Passwort-Feld ohnehin nur „set/unset" — im gssapi-Modus wird
  es nicht mehr gelesen.

---

## 7. Neu bauen & starten

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml -f docker-compose.selfsigned.yml -f docker-compose.build.yml build magister-api
docker compose -f docker-compose.yml -f docker-compose.selfsigned.yml up -d magister-api
```

---

## 8. Verifizieren (in dieser Reihenfolge)

```bash
# a) Keytab im Container lesbar + korrekter Prinzipal/KVNO:
docker compose exec magister-api klist -k /etc/magister/krb5.keytab

# b) Kann der Container ein Ticket für den DC-SPN holen? (KVNO-Abfrage)
docker compose exec -e KRB5_CLIENT_KTNAME=/etc/magister/krb5.keytab \
  magister-api kvno ldap/dc1.schule.local

# c) Funktionaler Bind-Test (Admin-Session):
curl -sk -X POST -H "Cookie: session=…" https://<host>/api/admin/ad-test | jq .
#   → {"ok": true, "detail": "ad_ok"}

# d) Echter Lauf: einen Sync bzw. einen kleinen Provisioning-Testimport machen,
#    danach die Logs auf ldap_bind_failed prüfen:
docker compose logs --tail=100 magister-api | grep -i bind
```

Erst wenn (c) `ok: true` liefert, ist die Umstellung erfolgreich.

---

## 9. Zurückrollen (jederzeit möglich)

Haken wieder entfernen (bzw. `MAGISTER_AD_BIND_MODE` löschen → Default `simple`),
Bind-DN + Passwort wieder eintragen, `up -d`. Kein DB-/Migrations-Eingriff.

---

## 10. Keytab-Rotation

`msktutil` rotiert das Konto-Passwort und schreibt den Keytab neu — per Host-Cron:
```bash
# z. B. wöchentlich, /etc/cron.d/magister-keytab:
0 3 * * 1 root msktutil update --auto-update \
  --keytab /etc/magister/krb5.keytab --computer-name SVC-MAGISTER \
  && chown 1000:1000 /etc/magister/krb5.keytab && chmod 600 /etc/magister/krb5.keytab
```
Der read-only gemountete Keytab wird automatisch aktuell; nur falls ein
Ticket-Cache klemmt: `docker compose restart magister-api`.

---

## 11. Troubleshooting

| Symptom (Log/Fehler) | Ursache | Fix |
|---|---|---|
| `Cannot contact any KDC for realm` | KDC nicht erreichbar / falscher Realm in krb5.conf | `krb5.conf` prüfen, DC-Erreichbarkeit (Port 88) |
| `Clock skew too great` | Zeit driftet > 5 Min | NTP auf Host **und** DC synchronisieren |
| `Server ldap/… not found in Kerberos database` | SPN/DNS: DC nur als IP, oder fehlender PTR | `MAGISTER_AD_DCS` = FQDN, Reverse-DNS setzen |
| `Preauthentication failed` / `KVNO mismatch` | Keytab veraltet (nach Rotation) | Keytab neu ziehen (`msktutil update`), Container neu starten |
| `Permission denied` beim Keytab | Datei nicht für uid 1000 lesbar | `chown 1000:1000` + `chmod 600` (Schritt 5) |
| `ad_bind_failed` trotz ok Ticket | Delegation fehlt in der OU | Rechte aus Schritt 3 setzen |

---

## Kurz-Checkliste

- [ ] Host joined, NTP synchron, DC per FQDN + PTR auflösbar, LDAPS 636 offen
- [ ] `msktutil create` → Keytab unter `/etc/magister/krb5.keytab`
- [ ] OU-Delegation: Benutzer anlegen + Passwort zurücksetzen
- [ ] `MAGISTER_AD_DCS` = FQDNs
- [ ] Keytab `chown 1000:1000` + `chmod 600`, in Container gemountet, `KRB5_CLIENT_KTNAME` gesetzt
- [ ] Haken „Kerberos/GSSAPI" in der UI (oder `MAGISTER_AD_BIND_MODE=gssapi`)
- [ ] Bind-DN/Passwort geleert
- [ ] `build` + `up -d`
- [ ] `klist -k`, `kvno`, `/api/admin/ad-test` = ok, Testlauf ohne `bind_failed`
