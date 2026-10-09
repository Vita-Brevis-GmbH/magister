# Runbook · Produktionsserver von Null (Ubuntu 26.04)

> Die gehostete Magister-Plattform auf **einem** Server in der DMZ: Konsole,
> Datenebene, Kundenseiten mit öffentlich gültigen Zertifikaten.
> Derselbe Aufbau wie in [plattform-auf-einem-host.md](plattform-auf-einem-host.md),
> mit `--art prod`. Referenz: ADR-0013, ADR-0014, ADR-0015.

## 0 · Die Namen auf einen Blick

| Was | Name | Port | Erreichbar von |
|---|---|---|---|
| Kundenseiten | `<kunde>.mgmt.vitabrevis.ch` (z. B. `gmp.mgmt.vitabrevis.ch`) | 443 (+80 für Let's Encrypt) | Internet |
| Connector-Kanal (AD-Agent auf dem DC) | `connect.mgmt.vitabrevis.ch` | 46200 | Internet (Kunden-DCs) |
| Konsole (Cockpit) | `https://mgmt.int.vitabrevis.ch:4444` (auch `konsole.mgmt.vitabrevis.ch`) | 4444 | **nur intern** (Verwaltungsnetz/VPN) |
| Server selbst | Hostname `mgmt`, FQDN `mgmt.int.vitabrevis.ch` | 22 | nur intern |

**Zertifikate:**

- **Kundenseiten:** Let's Encrypt, automatisch je Kunde.
  - Euer Wildcard `*.vitabrevis.ch` deckt nur **eine** Ebene ab. `mgmt.vitabrevis.ch` wäre gedeckt, `gmp.mgmt.vitabrevis.ch` nicht. Ein Browser würde dort warnen.
  - Wer lieber ein gekauftes Zertifikat nimmt, braucht eines für `*.mgmt.vitabrevis.ch` (§9).
- **Konsole und Connector:** Zertifikate aus der Plattform-CA.
  - `root.pem` kommt auf die Admin-Geräte und auf die DCs (`enroll --ca`).

Im Folgenden steht **`<PRIVATE_IP>`** für die feste private Adresse des
Servers in der DMZ und **`<PUBLIC_IP>`** für die öffentliche Adresse der
Firewall.

## 1 · Server

- Ubuntu Server 26.04 LTS, minimal, mit OpenSSH.
- Empfohlen sind 4 vCPU, 8 GB RAM und 80 GB Platte. Der Bau der Abbilder braucht anfangs am meisten.
- Netz: feste IP `<PRIVATE_IP>`, Hostname `mgmt`:

```bash
sudo hostnamectl set-hostname mgmt
# /etc/hosts: <PRIVATE_IP>  mgmt.int.vitabrevis.ch mgmt
```

## 2 · DNS und Firewall (vor dem Aufbau)

**Öffentlicher DNS** (Zone `vitabrevis.ch`):

| Eintrag | Typ | Ziel |
|---|---|---|
| `*.mgmt.vitabrevis.ch` | A | `<PUBLIC_IP>` |

Der eine Platzhalter-Eintrag deckt alle Kunden und `connect.` ab. Neue Kunden
brauchen **keinen** DNS-Eintrag mehr.

**Interner DNS** (Zone `int.vitabrevis.ch`, und eine Ausnahme für die Konsole):

| Eintrag | Typ | Ziel |
|---|---|---|
| `mgmt.int.vitabrevis.ch` | A | `<PRIVATE_IP>` |
| `konsole.mgmt.vitabrevis.ch` | A | `<PRIVATE_IP>` (optional; die Konsole ist auch unter `mgmt.int…` erreichbar) |
| `*.mgmt.vitabrevis.ch` | A | `<PRIVATE_IP>` (optional, gegen Hairpin-NAT für interne Aufrufe der Kundenseiten) |

**Firewall, eingehend** (NAT `<PUBLIC_IP>` → `<PRIVATE_IP>`):

| Port | Quelle | Wofür |
|---|---|---|
| TCP 443 | Internet | Kundenseiten |
| TCP 80 | Internet | Let's Encrypt (HTTP-01) und Umleitung auf HTTPS |
| TCP 46200 | Internet (oder nur die IPs der Kunden-DCs) | Connector-Kanal |
| TCP 4444 | **nur** Verwaltungsnetz/VPN | Konsole |
| TCP 22 | **nur** Verwaltungsnetz/VPN | SSH |

**Firewall, ausgehend** (TCP 443): `download.docker.com`,
`registry-1.docker.io` (+ `*.docker.io`, `production.cloudflare.docker.com`),
`ghcr.io`, `github.com` (+ `objects.githubusercontent.com`), `pypi.org`
(+ `files.pythonhosted.org`), `registry.npmjs.org`,
`acme-v02.api.letsencrypt.org`, `login.microsoftonline.com`; dazu
`ntp.ubuntu.com` (UDP 123) und die Ubuntu-Spiegel (80/443).

> Docker veröffentlicht Ports an `ufw`/`iptables` des Hosts vorbei. Die
> Schutzschicht ist deshalb die Firewall der DMZ, nicht der Host. Die Konsole
> lauscht ohnehin nur auf `<PRIVATE_IP>:4444`.

## 3 · Repository holen

Wer das Repository nicht schon hat: Personal Access Token auf GitHub
(fine-grained, nur `Vita-Brevis-GmbH/magister`, **Contents: read**).

```bash
sudo mkdir -p /opt/magister && sudo chown "$USER" /opt/magister
git clone --branch claude/multitenant-capability-planning-t6mygz \
  https://github.com/Vita-Brevis-GmbH/magister.git /opt/magister
# Benutzername: GitHub-Login, Passwort: der Token
```

Solange PR #57 nicht gemergt ist, gilt der Branch oben. Danach `main`
(`git switch main`).

## 4 · Host vorbereiten

```bash
cd /opt/magister
sudo ./scripts/prod-host-vorbereiten.sh --benutzer "$USER"
# abmelden und neu anmelden (Gruppe docker)
./scripts/prod-host-vorbereiten.sh --nur-pruefen
```

Das Skript erledigt:

- Systemupdate.
- Docker Engine mit compose- und buildx-Plugin.
- Begrenzte Docker-Protokolle.
- Automatische Sicherheitsupdates.
- Zeitzone und Zeitabgleich.

Danach prüft es die freien Ports und die ausgehenden Verbindungen. Ein
Hinweis „nicht erreichbar“ bedeutet: die Firewall nach §2 nachziehen. Läuft
der Weg ins Internet über einen Proxy, `HTTPS_PROXY` setzen. Docker braucht
ihn zusätzlich unter `/etc/systemd/system/docker.service.d/proxy.conf`.

## 5 · Plattform aufbauen

```bash
cd /opt/magister
./scripts/plattform-aufbau.sh up --art prod \
  --domaene mgmt.vitabrevis.ch \
  --bind <PRIVATE_IP> \
  --zusatzname mgmt.int.vitabrevis.ch \
  --acme-mail <betrieb@vitabrevis.ch>
```

Die Angaben landen in `plattform/plattform.conf`. Jedes spätere `update`
liest sie von dort.

Was `--art prod` anders macht als der Testaufbau:

- **Keine Demo-Kunden.** Kunden legt man in der Konsole an (§6).
- **Let's Encrypt für die Kundenseiten.** Caddy fragt vor jedem Zertifikat die Datenebene (`/tls/ask`). Nur Namen von angelegten Kunden bekommen eines.
- **Konsole fest auf `<PRIVATE_IP>`.** Die Datenebene erreicht sie über einen festen Eintrag (`docker-compose.konsole-adresse.yml`), nicht über den DNS. Der öffentliche Platzhalter zeigt auf die Firewall, und dort ist 4444 zu.
- **127.0.0.1 wird abgewiesen.** An Loopback käme die Datenebene nicht heran.

Der erste Aufbau dauert 10–20 Minuten, weil alle Abbilder gebaut werden. Am
Ende steht eine Liste offener Schritte. Was erledigt ist, fehlt darin.

## 6 · Konsole und erster Kunde

**Operator anlegen.** Das Passwort wird abgefragt, den TOTP-Code richtet man
beim ersten Login ein.

```bash
./scripts/plattform-aufbau.sh operator --upn vorname.nachname@vitabrevis.ch \
  --name "Vorname Nachname" --set-password
```

**`root.pem` auf dem Admin-Gerät** vertrauen, damit der Browser die Konsole
ohne Warnung zeigt. Die Datei ist `/opt/magister/plattform/certs/root.pem`.

```powershell
# Windows, als Administrator (oder per GPO verteilen):
certutil -addstore -f Root C:\Temp\root.pem
```

Danach `https://mgmt.int.vitabrevis.ch:4444` öffnen.

**Neustart und Update aus der Konsole** einrichten (einmalig, als root):

```bash
sudo ./scripts/plattform-aufbau.sh ops-agent
```

**Agenten-MSI** fürs Cockpit holen. Den Token legt man einmal ab: es reicht
ein GitHub-Token mit **Actions: read**.

```bash
./scripts/agentenpakete.sh token
./scripts/agentenpakete.sh holen
```

**Ersten Kunden** in der Konsole anlegen:

1. Kunden → Neu, Kürzel `gmp`, Hostname `gmp.mgmt.vitabrevis.ch`.
2. Auf der Datenebene eintragen:

   ```bash
   ./scripts/plattform-aufbau.sh kunde-anbinden gmp
   ```

   Das setzt DSN und Kundenschlüssel in `deploy/compose/.env` und startet die
   API neu.
3. Prüfen, **von aussen** (Handy-Hotspot oder ein anderer Server):

   ```bash
   curl -sI https://gmp.mgmt.vitabrevis.ch | head -1
   echo | openssl s_client -connect gmp.mgmt.vitabrevis.ch:443 \
     -servername gmp.mgmt.vitabrevis.ch 2>/dev/null | openssl x509 -noout -issuer -dates
   # issuer: Let's Encrypt
   ```

Der erste Aufruf dauert ein paar Sekunden, weil Caddy das Zertifikat holt.
Protokoll:

```bash
docker logs magister-caddy-1 2>&1 | grep -iE "obtain|certificate|error" | tail
```

## 7 · Nach der Einrichtung: Schlüssel weg vom Server

Die Plattform-CA ist auf dem Server entstanden. Ihre Wurzel signiert die
Zertifikate der Konsole und des Connector-Kanals.

1. Diese Dateien in den Passwortspeicher bzw. den Tresor übernehmen:
   - `plattform/plattform.conf`
   - `plattform/certs/` (ganz)
   - `cockpit/deploy/.env`
   - `deploy/compose/.env`

   Besonders wichtig: in `deploy/compose/.env` stehen die
   **Kundenschlüssel** (`MAGISTER_TENANT_AUDIT_KEY_*`). Ohne sie sind die
   verschlüsselten Daten eines Kunden nach einem Verlust des Servers
   unlesbar.
2. Danach vom Server löschen:

   ```bash
   shred -u plattform/certs/root-key.pem
   shred -u plattform/certs/backup-age.key   # privater Teil der Sicherungen
   ```

   Gebraucht wird `root-key.pem` nur, wenn sich ein Name ändert. Dann sagt
   `up` das ausdrücklich, und man legt die Datei vorübergehend zurück. Die
   Prüfung der Sicherungen (`backup-pruefer`) richtet man auf einem
   separaten Sicherungs-Host ein, nicht hier.

Die vollständige Trennung, mit einer Wurzel aus der Zeremonie auf einem
Offline-Rechner, beschreibt [platform-ca.md](platform-ca.md).

## 8 · Entra und AD-Connector testen

- **Entra:**
  - Cockpit → Kunde `gmp` → Einstellungen → Entra ID → **„? Hilfe / Help“**.
  - Die Umleitungs-URI ist `https://gmp.mgmt.vitabrevis.ch/api/auth/callback`.
- **AD-Connector auf dem DC:**
  - `root.pem` im Cockpit herunterladen (Kunde → Connector).
  - Auf dem DC einschreiben:

    ```powershell
    magister-connector enroll --endpoint https://connect.mgmt.vitabrevis.ch:46200 --ca C:\Temp\root.pem
    ```

  - Der DC braucht ausgehend TCP 46200 zu `<PUBLIC_IP>`. Alles Weitere steht in `agent/packaging/windows/INSTALL.txt`.

## 9 · Statt Let's Encrypt: gekauftes Wildcard

Nur mit einem Zertifikat für **`*.mgmt.vitabrevis.ch`**. `*.vitabrevis.ch`
reicht nicht.

```bash
mkdir -p plattform/kundenzertifikat
cp fullchain.pem plattform/kundenzertifikat/tenants.pem     # Zertifikat + Zwischenzertifikate
cp privkey.pem   plattform/kundenzertifikat/tenants-key.pem # ohne Passwort
./scripts/plattform-aufbau.sh up --tls eigen
```

`up` prüft vor dem Start:

- dass das Zertifikat `*.mgmt.vitabrevis.ch` abdeckt;
- dass es nicht in den nächsten 14 Tagen abläuft.

Die Erneuerung macht man von Hand: neue Dateien hinein, dann erneut `up`.

## 10 · Betrieb

```bash
cd /opt/magister
./scripts/plattform-aufbau.sh status     # Container und Zustand je Kunde
git pull && ./scripts/plattform-aufbau.sh update
./scripts/plattform-aufbau.sh konfig     # welche Angaben gelten
```

| Symptom | Ursache | Abhilfe |
|---|---|---|
| Kundenseite: Zertifikatsfehler, Caddy-Log `no solvers available` oder `timeout during connect` | Port 80 nicht weitergeleitet oder DNS zeigt nicht auf `<PUBLIC_IP>` | §2 prüfen, dann die Seite neu laden |
| Caddy-Log: `/tls/ask` lehnt den Namen ab | Kunde nicht aktiv oder Hostname falsch angelegt | Konsole: Kunde aktiv? Hostname genau `<kunde>.mgmt.vitabrevis.ch`? |
| Caddy-Log `too many certificates` | Rate-Limit von Let's Encrypt (wiederholte Fehlversuche) | Ursache beheben, eine Stunde warten |
| Kundenseite 503 „maintenance“, `status`: keine Kunden | Datenebene erreicht die Konsole nicht | `docker exec magister-magister-api-1 getent hosts konsole.mgmt.vitabrevis.ch` muss `<PRIVATE_IP>` zeigen; sonst `up` erneut |
| Konsole 421 | Aufruf unter einem Namen, der nicht im Zertifikat steht | `https://mgmt.int.vitabrevis.ch:4444` verwenden |
| Agent: `CERTIFICATE_VERIFY_FAILED` | `root.pem` fehlt beim `enroll` oder ein Proxy bricht TLS auf | `enroll --ca …\root.pem`; 46200 am Proxy vorbei |
