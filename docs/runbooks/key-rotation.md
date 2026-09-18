# Runbook: Key Rotation

Drei Schlüssel-Klassen in Magister:

| Schlüssel | Zweck | Rotations-Frequenz |
|---|---|---|
| `MAGISTER_AUDIT_KEY` | `pgcrypto`-Verschlüsselung der Audit-Payloads | Jährlich oder bei Kompromittierung |
| OIDC-Client-Secret (Entra) | Auth gegen Entra ID | Halbjährlich |
| AD-Bind-Passwort | LDAPS-Bind des Service-Accounts | Jährlich |
| Operator-Signierschlüssel (ADR-0019) | Signiert die Einlösescheine für einen Operator-Zugriff | Nur bei Kompromittierung oder Personalwechsel |

---

## 1. `MAGISTER_AUDIT_KEY` rotieren

Das ist die heikelste Operation: alle Audit-Events werden mit pgcrypto verschlüsselt; ein nahtloser Wechsel braucht **Re-Encryption** der bestehenden Daten.

### Vorbereitung

```bash
# Neuen Key generieren
NEW_KEY=$(openssl rand -base64 48)
echo "$NEW_KEY" | op create item Password --vault="Vita-Brevis" \
  --title="magister-audit-key-<schulträger>-$(date +%Y%m)"
```

### Re-Encryption-Script

```bash
# Maintenance-Mode (Web abklemmen, API für Schreib-Operationen pausieren)
docker compose stop web
docker compose exec api python -m magister_api.tools.rotate_audit_key \
  --old-key "$OLD_KEY" --new-key "$NEW_KEY" --batch-size 1000
```

Das CLI iteriert über `audit_events`, entschlüsselt mit altem Key, verschlüsselt mit neuem Key. Läuft idempotent (markiert verarbeitete Rows in `audit_events.rotation_marker`).

### Cutover

```bash
# .env updaten
sed -i "s/^MAGISTER_AUDIT_KEY=.*/MAGISTER_AUDIT_KEY=$NEW_KEY/" /etc/magister/.env
docker compose up -d
# Smoke: ein Audit-Event lesen
curl -sf -H "Cookie: session=..." https://<host>/api/audit/events?limit=1 | jq .
```

### Rollback

Solange `rotation_marker` nicht alle Rows abgedeckt hat: alten Key wieder in `.env` setzen, Re-Run mit umgekehrten Parametern.

---

## 2. OIDC-Client-Secret rotieren

Entra erlaubt mehrere gültige Secrets parallel — nahtlose Rotation:

```bash
# 1. In Entra Admin Center: neues Client-Secret erzeugen (Gültigkeit 180 Tage)
# 2. .env updaten:
sed -i "s/^MAGISTER_OIDC_CLIENT_SECRET=.*/MAGISTER_OIDC_CLIENT_SECRET=$NEW_SECRET/" /etc/magister/.env
# 3. API neu starten:
docker compose restart api
# 4. Smoke: Login mit Test-User
# 5. Altes Secret in Entra deaktivieren
```

---

## 3. AD-Bind-Passwort rotieren

```bash
# In AD: Service-Account-Passwort ändern
# .env updaten:
sed -i "s/^MAGISTER_AD_BIND_PASSWORD=.*/MAGISTER_AD_BIND_PASSWORD=$NEW_PW/" /etc/magister/.env
docker compose restart api
# Smoke: manueller AD-Sync triggern
curl -sf -X POST -H "Cookie: session=..." https://<host>/api/admin/ad-sync | jq .
```

---

## 4. Operator-Signierschlüssel wechseln (ADR-0019)

Ein Ed25519-Paar: die **Konsole** hält den privaten Teil
(`COCKPIT_OPERATOR_SIGNING_KEY`, ein Dateipfad), jede **Datenebene** den
öffentlichen (`MAGISTER_OPERATOR_PUBLIC_KEY`, der PEM-Text selbst).

```bash
# Neues Paar (auf dem Konsolen-Server, als root)
umask 077
openssl genpkey -algorithm ed25519 -out /etc/magister/operator-signing.pem.new
openssl pkey -in /etc/magister/operator-signing.pem.new -pubout
```

Reihenfolge, und sie ist nicht beliebig: **erst** den öffentlichen Schlüssel
bei allen Kunden austauschen, **dann** den privaten in der Konsole. Umgekehrt
stellt die Konsole Scheine aus, die niemand einlösen kann — und das merkt man
im Support-Fall, also zum schlechtesten Zeitpunkt.

Kein Re-Encryption, keine Migration, kein Datenverlust: ein Einlöseschein ist
sechzig Sekunden gültig. Was während des Wechsels unterwegs ist, wird
abgewiesen; ein neuer Schein löst das.

**Wenn der private Schlüssel verloren geht:** kein Operator-Zugriff mehr, bis
ein neues Paar verteilt ist. Kein Datenverlust — aber ein Handgriff, und
deshalb gehört der Schlüssel in die Sicherung des Konsolen-Servers
(`/etc/magister/`, siehe `disaster-recovery.md`).

**Wenn er in falsche Hände gerät:** der Inhaber kann Zugriffe auf jeden Kunden
ausstellen. Sie sind lesend und stehen in jedem Kundenprotokoll (ADR-0019 D1,
D6) — aber der Wechsel ist sofort fällig, und die Zugriffslisten der Kunden
sind danach durchzusehen.

---

## 5. `COCKPIT_SECRET_KEY` wechseln (ADR-0020 D2)

Damit ist das TOTP-Geheimnis jedes Konsolen-Operators in der
Konsolen-Datenbank verschlüsselt (pgcrypto, wie `MAGISTER_AUDIT_KEY` in der
Datenebene).

**Ehrlich zuerst:** anders als bei den vier Schlüsseln oben gibt es hier
**keinen** Weg ohne Zutun der Personen. Der alte Wert entschlüsselt die
Geheimnisse, der neue nicht — und ein Re-Encryption-Lauf bräuchte beide
Schlüssel gleichzeitig auf dem Server, also genau das, was vermieden werden
soll. Der Wechsel heisst deshalb: **jeder Operator richtet seinen zweiten
Faktor neu ein.** Bei zwei Personen ist das ein Termin, keine Migration.

```bash
# 1. Neuen Wert erzeugen und in die .env der Konsole
openssl rand -base64 48

# 2. Die Geheimnisse aller Operatoren leeren — sie sind mit dem alten Wert
#    verschlüsselt und nach dem Wechsel unbrauchbar. Ohne diesen Schritt
#    scheitert jede Anmeldung an einem Entschlüsselungsfehler statt an einem
#    ehrlichen „richte neu ein“.
docker compose exec postgres psql -U cockpit -d cockpit -c \
  "UPDATE console_operators SET totp_secret_enc = NULL, totp_confirmed_at = NULL,
          totp_last_step = NULL, recovery_codes = '[]'"

# 3. Konsole neu starten, dann melden sich beide Operatoren an und richten
#    den zweiten Faktor neu ein (Runbook konsolen-operator.md, Abschnitt 4).
docker compose restart api
```

Solange niemand wieder eingerichtet ist, führt der Weg herein über den
Bootstrap-Token. Den also **vor** dem Wechsel zur Hand haben.

**Wenn er verloren geht:** kein Operator kommt mehr über den zweiten Faktor
herein; dieselbe Behandlung wie oben, plus Bootstrap-Token als Einstieg.
Deshalb gehört er in die Sicherung des Konsolen-Servers — ohne ihn ist eine
wiederhergestellte Konsole eine Konsole ohne Anmeldung.

**Wenn er in falsche Hände gerät:** er allein nützt nichts. Ein TOTP-Geheimnis
daraus braucht zusätzlich Lesezugriff auf die Konsolen-Datenbank, und eine
Anmeldung zusätzlich ein gültiges Client-Zertifikat und Netzzugang auf die
interne Adresse. Fällig ist der Wechsel trotzdem — zusammen mit dem Durchsehen,
wie er abgeflossen ist.

---

## Audit-Trail

Jede Key-Rotation ist meldepflichtig:

```bash
# Audit-Event manuell einfügen via SQL (mit gerade rotiertem Key signiert)
docker compose exec api python -m magister_api.tools.audit_emit \
  --action key_rotated --target-kind audit_key \
  --payload '{"key_id_new": "magister-audit-key-<schulträger>-202606", "rotated_by": "<your-upn>"}'
```

Eintrag wandert ins Audit-Listing für die Schulleitung (revDSG-Nachweis).

---

## Kalender

| Monat | Was | Verantwortlich |
|---|---|---|
| Januar | AD-Bind-PW + OIDC-Secret | Ops-Team |
| Juli | OIDC-Secret | Ops-Team |
| Quartalsweise Q1 | Audit-Key-Drill auf Staging | Ops-Team |
| Jährlich | Audit-Key auf Produktion | Ops-Team + CTO Sign-off |
