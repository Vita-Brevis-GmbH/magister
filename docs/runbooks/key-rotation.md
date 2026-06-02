# Runbook: Key Rotation

Drei Schlüssel-Klassen in Magister:

| Schlüssel | Zweck | Rotations-Frequenz |
|---|---|---|
| `MAGISTER_AUDIT_KEY` | `pgcrypto`-Verschlüsselung der Audit-Payloads | Jährlich oder bei Kompromittierung |
| OIDC-Client-Secret (Entra) | Auth gegen Entra ID | Halbjährlich |
| AD-Bind-Passwort | LDAPS-Bind des Service-Accounts | Jährlich |

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
