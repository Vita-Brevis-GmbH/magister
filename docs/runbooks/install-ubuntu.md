# Installation auf Ubuntu — End-to-End

Vom leeren Ubuntu 24.04 LTS bis zur lauffähigen Magister-Installation für
einen Schulträger. Geht auch auf Debian 12 (Codename `bookworm`) durch —
ersetze in den Docker-Repo-URLs `ubuntu` durch `debian`.

Geschätzter Zeitaufwand: 30-60 Minuten ohne ACME-Wartezeit; +1-2 h für
die Entra-ID + AD-Vorbereitung wenn die noch nicht da sind.

---

## 0. Was du vorher bereit haben musst

| Item | Wozu |
|---|---|
| Ubuntu-VM 24.04 LTS, ≥ 2 vCPU, ≥ 4 GB RAM, ≥ 20 GB Disk | Compose-Stack |
| Öffentlicher FQDN (z. B. `magister.schule.example.ch`) | Caddy holt darüber Let's-Encrypt-Zertifikate |
| DNS A-/AAAA-Record FQDN → öffentliche IP der VM | ACME-Challenge per HTTP-01 |
| Ports 80 + 443 von außen erreichbar | ACME + Web-Zugriff |
| Entra-ID-Tenant + App-Registrierung *(siehe §3 — kann später nachgereicht werden, der lokale Break-Glass-Admin reicht für Day-1)* | OIDC-Login |
| Erreichbares on-prem AD über LDAPS 636 *(siehe §4 — auch später möglich)* | User-Sync + PW-Reset |

---

## 1. System vorbereiten

```bash
sudo apt-get update
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    git \
    ufw \
    chrony

# Zeit synchron halten (für TLS + AD wichtig)
sudo systemctl enable --now chrony

# Firewall: nur SSH + Web öffnen
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status
```

Hostname stimmig setzen (taucht in HSTS-Headers + Audit-Logs auf):

```bash
sudo hostnamectl set-hostname magister
echo "127.0.1.1 magister.$(dnsdomainname 2>/dev/null || echo example.ch) magister" \
    | sudo tee -a /etc/hosts
```

DNS-Check (muss auf die öffentliche IP deiner VM zeigen):

```bash
dig +short A magister.schule.example.ch    # → die VM-IP
```

---

## 2. Docker + Compose installieren

```bash
# Docker-Repo eintragen
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# Den eigenen User in die docker-Gruppe, dann neu einloggen
sudo usermod -aG docker "$USER"
newgrp docker   # oder ab- und neu anmelden

# Test
docker --version
docker compose version
```

---

## 3. (Vorbereitung) Entra-ID App-Registrierung

Magister meldet Lehrer:innen + Admins per OIDC gegen Entra ID an. Falls
du das später konfigurieren willst: überspring diesen Abschnitt und nutz
in §6 den lokalen Break-Glass-Admin.

1. Azure Portal → **Microsoft Entra ID → App registrations → New registration**
2. Name: `Magister-<Schulträger>`
3. Supported account types: *Accounts in this organizational directory only*
4. Redirect URI (Web): `https://magister.schule.example.ch/api/auth/callback`
5. Nach dem Anlegen merken:
   - **Application (client) ID** → wird in §6 zu `MAGISTER_OIDC_CLIENT_ID`
   - **Directory (tenant) ID** → wird Teil von `MAGISTER_OIDC_ISSUER`
     (`https://login.microsoftonline.com/<tenant-id>/v2.0`)
6. **Certificates & secrets → New client secret** → Wert kopieren →
   `MAGISTER_OIDC_CLIENT_SECRET`
7. **API permissions** → Microsoft Graph delegated: `openid`, `profile`, `email`
8. **Authentication → ID tokens** anhaken

---

## 4. (Vorbereitung) AD-Service-Account + Delegationen

Magister bindet auf der Schulträger-Domäne mit einem dedizierten
Service-Account (kein Domain-Admin). Wenn AD noch nicht steht: später, dann
ab §6 den GUI-Editor nutzen.

### 4.1 Service-Account anlegen

Im AD einen normalen User anlegen, z. B.
`CN=magister-svc,OU=ServiceAccounts,DC=schule,DC=local`. Kennwort nie
ablaufend, "User cannot change password".

### 4.2 Delegationen auf der Schüler:innen-OU

Rechtsklick auf die Schüler-OU → **Delegate Control**. Für den
`magister-svc` folgende **Custom Tasks** delegieren:

| Recht | Wofür |
|---|---|
| `Read all properties` | User-Sync |
| `Reset Password` (Extended Right `00299570-246d-11d0-a768-00aa006e0529`) | Schüler-PW-Reset |
| `Write Account Restrictions` | `pwdLastSet=0` (force-change) |
| `Write displayName` | User-Attribut-Edit (Phase 2) |
| `Write streetAddress`, `Write l`, `Write postalCode`, `Write co` | Adresse |
| `Write mail` | Mail-Edit |

Für die **Lehrpersonen-OU** zusätzlich (nur wenn SMI/Admin das ändern
darf — Phase 2):

| Recht | Wofür |
|---|---|
| `Write userPrincipalName` | UPN-Wechsel (admin-only) |
| `Write sAMAccountName` | Kurz-Username-Wechsel (admin-only) |

### 4.3 Optional: Computer-OU für Geräte-Zuordnung (Phase 4)

Wenn Magister Geräte den Usern zuordnen soll:
- `Read all properties` auf der Computer-OU
- Sicherstellen dass `managedBy` auf den User-DN gepflegt ist
  (z. B. via Intune-Workflow oder manuell)

Bleibt das aus → Geräte-Sync schaltet sich still ab, alles andere geht
normal.

### 4.4 LDAPS-Vorbereitung

Magister verbindet ausschließlich über LDAPS 636 mit `CERT_REQUIRED`.
Die DC's müssen daher ein gültiges TLS-Cert mit dem DC-FQDN als CN/SAN
ausgespielt haben. Ein selbst-signiertes Cert geht — du musst dann das
CA-Bundle auf den Magister-Host kopieren und in §6 als
`MAGISTER_AD_CA_BUNDLE_PATH` setzen.

```bash
# Beispiel: CA-Bundle der Schul-Root-CA in /etc/magister/ablegen
sudo mkdir -p /etc/magister
sudo cp /path/to/schule-rootca.pem /etc/magister/ad-ca-bundle.pem
sudo chmod 644 /etc/magister/ad-ca-bundle.pem
```

---

## 5. Repository klonen + Konfiguration vorbereiten

```bash
cd /opt
sudo git clone https://github.com/vita-brevis-gmbh/magister.git
sudo chown -R "$USER":"$USER" magister
cd magister/deploy/compose
cp .env.example .env
```

### 5.1 Geheimnisse erzeugen

Drei zufällige 48-Byte-Secrets:

```bash
python3 -c "import secrets; print('MAGISTER_AUDIT_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('MAGISTER_SESSION_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('MAGISTER_CSRF_SECRET=' + secrets.token_urlsafe(48))"
```

Diese Werte ins `.env` übernehmen.

> **Wichtig:** `MAGISTER_AUDIT_KEY` darf nach Inbetriebnahme **niemals**
> rotiert werden — bestehende `audit_events`-Rows sind damit verschlüsselt
> und werden sonst unlesbar. Backup des Keys gehört in den Schulträger-Safe.

### 5.2 Lokales Break-Glass-Admin-Konto erzeugen

Den Hash direkt mit dem produktiven API-Image erzeugen — das nutzt exakt
die getunten argon2id-Parameter, die der Login-Pfad erwartet (kein
Checkout, kein `pip install` nötig; Plaintext geht nirgends auf Disk):

```bash
printf '%s' 'DEIN_PASSWORT' | docker run --rm -i --entrypoint python \
    ghcr.io/vita-brevis-gmbh/magister-api:latest \
    -c 'import sys; from magister_api.auth.passwords import hash_password; print(hash_password(sys.stdin.readline().rstrip("\n")))'
# → $argon2id$v=19$m=65536,t=3,p=4$...
```

Den Hash + Username ins `.env`. **Wichtig — `$` verdoppeln:** docker compose
interpoliert `$` in `.env`-Werten; ein roher argon2-Hash kommt sonst korrupt
am Container an und der Login scheitert kommentarlos. Jedes `$` als `$$`
schreiben:

```env
MAGISTER_LOCAL_ADMIN_USERNAME=admin
MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=$$argon2id$$v=19$$m=65536,t=3,p=4$$...
```

> Das Plaintext-PW wird **nicht** auf Disk geschrieben. Du brauchst es
> später beim ersten Login — also kurz notieren und nach §6.4 sicher löschen.
> Noch einfacher als der manuelle Weg: `scripts/install-magister.sh` erledigt
> Hashing + Escaping automatisch.

### 5.3 `.env` Minimal-Set

```env
# --- Hosting ---
MAGISTER_PUBLIC_HOSTNAME=magister.schule.example.ch
MAGISTER_ACME_EMAIL=ops@schule.example.ch

# --- DB ---
POSTGRES_USER=magister
POSTGRES_PASSWORD=<starkes-pw>
POSTGRES_DB=magister

# --- Krypto / Sessions (aus 5.1) ---
MAGISTER_AUDIT_KEY=<48-byte url-safe>
MAGISTER_SESSION_SECRET=<48-byte url-safe>
MAGISTER_CSRF_SECRET=<48-byte url-safe>

# --- Break-Glass-Admin (aus 5.2; $ im Hash zu $$ verdoppeln!) ---
MAGISTER_LOCAL_ADMIN_USERNAME=admin
MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=$$argon2id$$v=19$$m=65536,t=3,p=4$$...

# --- Bootstrap-Admins (optional, kann auch via GUI nachgepflegt werden) ---
# Lehrpersonen-UPNs, die beim ersten OIDC-Login admin-Rechte bekommen
# MAGISTER_BOOTSTRAP_ADMINS=admin1@schule.example.ch

# --- LDAPS Cert-Pin (optional, empfohlen für Produktion) ---
# MAGISTER_AD_CA_BUNDLE_PATH=/etc/magister/ad-ca-bundle.pem

# OIDC + AD muss NICHT mehr im .env stehen — kommt ab §6.5 ins Admin-GUI
```

---

## 6. Stack hochfahren

```bash
cd /opt/magister/deploy/compose
docker compose pull
docker compose up -d
docker compose logs -f magister-api
```

Du solltest in den Logs sehen:

```
WARNING  Local admin seeded from MAGISTER_LOCAL_ADMIN_PASSWORD_HASH …
INFO     Application startup complete
```

Caddy holt im Hintergrund das ACME-Zertifikat — kann 30-60 Sekunden
dauern. Sobald `caddy`-Logs `certificate obtained successfully` zeigen:

```bash
curl https://magister.schule.example.ch/healthz
# {"status":"ok","version":"0.1.0"}
```

### 6.1 Erste Anmeldung

Im Browser: **`https://magister.schule.example.ch/login`**

- Du siehst die lokale Login-Form (OIDC ist noch nicht konfiguriert)
- Mit `admin` + dem Klartext-PW aus §5.2 anmelden

### 6.2 OIDC + AD im GUI konfigurieren

**Administration → Systemeinstellungen** öffnen.

**Entra ID** (aus §3):
- Issuer-URL: `https://login.microsoftonline.com/<tenant-id>/v2.0`
- Client-ID: `<application-client-id>`
- Client-Secret: `<das geheime Wert aus §3 Schritt 6>`
- Redirect-URI: `https://magister.schule.example.ch/api/auth/callback`
- Scopes: `openid, profile, email`
- Bootstrap-Admins: `admin1@schule.example.ch` (CSV)

**Active Directory** (aus §4):
- Domain-Controller: `dc1.schule.local, dc2.schule.local` (CSV)
- Bind-DN: `CN=magister-svc,OU=ServiceAccounts,DC=schule,DC=local`
- Bind-Passwort: `<das PW des Service-Accounts>`
- Such-Basis (User): `OU=Magister,DC=schule,DC=local`
- Such-Basis (Computer): `OU=Computers,DC=schule,DC=local` *(optional, für Geräte-Sync)*
- Sync-Intervall: `15` (Minuten)

**Mail-Domains** (Pflicht wenn User-Mail/UPN editiert werden sollen):
- z. B. `schule.example.ch, lehrer.schule.example.ch` (CSV)

**Speichern.** Der OIDC- + AD-Client wird beim nächsten Request automatisch
neu instanziiert — kein Container-Restart.

### 6.3 Abmelden, mit Entra einloggen

Logout → erneut `/login` aufrufen → **"Mit Entra ID anmelden"**.
Du landest auf der Entra-Login-Seite, kommst mit gültigem Token zurück,
und Magister legt für deinen UPN die `role_assignments(role='admin', school_id=NULL)`
an (weil dein UPN in den Bootstrap-Admins steht).

### 6.4 Lokalen Admin deaktivieren

**Administration → Lokales Admin-Konto → Deaktivieren.**

Das Konto bleibt als Break-Glass in der DB, ist aber nicht mehr nutzbar
solange der Toggle aus ist. Das Plaintext-PW aus §5.2 jetzt sicher
löschen.

### 6.5 Schule(n) anlegen

Eine Schule pro Schul-Standort. Aktuell via SQL (eigene Admin-UI kommt
in M2):

```bash
docker compose exec postgres psql -U magister -d magister <<'SQL'
INSERT INTO schools (name, kuerzel, scope_short)
VALUES ('Schule Beispiel', 'BSP', 'BSP');
SQL
```

`scope_short` muss als OU-Pfad-Bestandteil im AD vorkommen, damit der
Sync User der richtigen Schule zuordnet. Beispiel: ein User-DN
`CN=Anna,OU=Students,OU=BSP,DC=schule,DC=local` matcht auf Schule
`scope_short=BSP`.

### 6.6 Ersten AD-Sync triggern

Eingeloggt als Admin im GUI → **Administration → AD-Sync starten**.

Oder via API:

```bash
curl -X POST https://magister.schule.example.ch/api/admin/ad-sync \
    -b magister_session=<sid> \
    -H "X-CSRF-Token: <csrf>"
# {"synced_count": 247, "device_count": 18, "school_partition": {"1": 247}}
```

Erfolgreich = User erscheinen in **`/users`**, "Letzter AD-Sync" im
Header zeigt den Zeitstempel.

Danach läuft der Sync **automatisch** im Intervall aus §6.2 (Sync-Intervall,
Default 15 min) — ein App-interner Hintergrund-Task erledigt das ohne
Container-Restart und ohne externen Cron. Der manuelle Trigger bleibt für
On-Demand-Syncs (z. B. direkt nach einer AD-Änderung). Im Betrieb prüfbar via:

```bash
# Scheduler-Lebenszeichen in den Logs:
docker compose logs magister-api | grep -i "ad-sync scheduler"
# Letzte automatische Läufe (Actor system:ad-sync-scheduler):
docker compose exec postgres psql -U magister -d magister -c \
  "SELECT ts, action FROM audit_events \
   WHERE actor_upn='system:ad-sync-scheduler' ORDER BY ts DESC LIMIT 5;"
```

Das Intervall lässt sich jederzeit unter **Administration → Systemeinstellungen**
ändern; der nächste Tick übernimmt den neuen Wert ohne Neustart.

### 6.7 SMI-Rollen vergeben (Schulträger-IT)

SMI ist die per-school Schulträger-IT-Rolle (cross-school User-Edit +
Teacher-PW-Reset). Aktuell wird sie via DB-Insert vergeben (eigenes
Grant-UI ist Roadmap M2):

```bash
# Pro Schule, die der SMI sehen darf, einen Eintrag:
docker compose exec postgres psql -U magister -d magister <<'SQL'
INSERT INTO role_assignments (ad_object_guid, school_id, role, granted_by)
SELECT
  (SELECT ad_object_guid FROM ad_user_cache WHERE upn = 'it-helpdesk@schule.example.ch'),
  s.id,
  'smi',
  'ops@example.ch'
FROM schools s;
SQL
```

Der/die SMI muss sich einmal aus- und neu anmelden, damit die Rolle in
die Session überschwappt.

---

## 7. Verifikation (Smoke-Test)

```bash
# 1) Health
curl https://magister.schule.example.ch/healthz
# {"status":"ok","version":"0.1.0"}

# 2) Auth-Capabilities (sieht der Login-Screen)
curl https://magister.schule.example.ch/api/auth/capabilities
# {"oidc_enabled":true,"local_login_enabled":false}

# 3) Logged-in /me (Cookie aus Browser kopieren oder per Login-Flow holen)
curl https://magister.schule.example.ch/api/auth/me \
    -b magister_session=<sid>
# {"upn":"...","is_admin":true,"roles":["admin"], ...}
```

Im Browser einmal durchklicken:
- `/classes` → mindestens die Demo-Klassen wenn geseedet, sonst leer
- `/users` → User aus dem AD-Sync, mit Avatar + Name + Status
- `/users/<guid>` → Edit-Formular mit allen vier Sektionen
- `/admin/settings` → die Felder, die du in §6.2 gepflegt hast

---

## 8. Backups

Der mitlaufende `pg-backup`-Sidecar schreibt täglich `pg_dump`s ins
Container-Volume:

```bash
# Schedule + Retention im .env steuern:
BACKUP_CRON="15 2 * * *"      # täglich 02:15 UTC
BACKUP_RETENTION_DAYS=14
```

Backups liegen im Volume `magister_pg_backups` unter
`/var/backups/magister`. Off-host sync ist **Ops-Aufgabe** — Beispiel
mit `restic`:

```bash
sudo apt-get install -y restic
sudo restic init --repo /backup/restic
sudo restic backup --repo /backup/restic \
    /var/lib/docker/volumes/magister_pg_backups/_data
```

> **Niemals** den `MAGISTER_AUDIT_KEY` zusammen mit dem `pg_dump` an
> dieselbe Stelle backuppen — das hebt die Encryption-at-Rest auf. Key
> getrennt im Schulträger-Safe.

---

## 9. Update auf eine neuere Version

```bash
cd /opt/magister
git pull
cd deploy/compose
docker compose pull
docker compose up -d
docker compose logs -f magister-api
# DB-Migrationen laufen im Lifespan automatisch.
```

Vor jedem Update: `docker compose exec postgres pg_dump -U magister magister > /tmp/pre-upgrade.sql`.

---

## 10. Troubleshooting-Schnellreferenz

| Symptom | Wahrscheinliche Ursache | Fix |
|---|---|---|
| Caddy bekommt kein Cert | DNS zeigt nicht auf VM, oder Port 80 blockiert | DNS prüfen (`dig`), `ufw allow 80/tcp` |
| `/users` ist leer | Kein AD-Sync gelaufen oder `ad_users_search_base` falsch | `docker compose logs magister-api`, in `/admin/settings` Such-Basis prüfen |
| Automatischer Sync läuft scheinbar nicht | AD noch nicht konfiguriert (Ticks werden übersprungen) oder Intervall zu hoch | `docker compose logs magister-api \| grep -i ad-sync`; Audit-Log auf Actor `system:ad-sync-scheduler` prüfen; Intervall in `/admin/settings` |
| OIDC-Callback → `user_not_synced` | Erster Login eines Nicht-Bootstrap-UPN bevor Sync gelaufen ist | Erst Sync starten ODER UPN in Bootstrap-Admins setzen |
| `503 ad_unavailable` bei PW-Reset | LDAPS-Pool down (alle DCs nicht erreichbar) oder Cert-Validation fehlgeschlagen | `openssl s_client -connect dc1:636` zum Cert prüfen; ggf. `MAGISTER_AD_CA_BUNDLE_PATH` setzen |
| `422 domain_not_allowed` beim User-Edit | UPN/Mail-Domain steht nicht in `mail_domains` | Admin → Systemeinstellungen → Mail-Domains ergänzen |
| `422 mail_domains_not_configured` | `mail_domains` ist leer | dito |
| `403 admin_only_field:upn,sam_account_name` | SMI versucht Login-Name zu ändern | Per Design admin-only — Admin-Account verwenden |
| `409 upn_conflict:<val>` | Ziel-UPN existiert bereits an anderem User | Anderen UPN wählen oder Konflikt-User erst migrieren |
| Audit-Reads liefern nichts | `MAGISTER_AUDIT_KEY` rotiert oder verloren | Aus Backup wiederherstellen — Audit-Rows sind sonst dauerhaft unlesbar |

---

## Querverweise

- Demo-Daten + Walkthrough: [`demo.md`](demo.md)
- Aufrüstung von Pre-M1.5-Installationen: [`upgrade-to-m1.5.md`](upgrade-to-m1.5.md)
- Architektur + Sicherheitsmodell: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- Niemals/Immer-Regeln + Coding-Konventionen: [`../../CLAUDE.md`](../../CLAUDE.md)
