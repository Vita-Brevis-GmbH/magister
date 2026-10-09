# Runbook · Produktionsserver von Null (Ubuntu 26.04)

> Die gehostete Magister-Plattform auf **einem** Server in der DMZ hinter der
> WAF: Konsole, Datenebene, Kundenseiten mit dem Wildcard `*.mgmt.vitabrevis.ch`.
> Derselbe Aufbau wie in [plattform-auf-einem-host.md](plattform-auf-einem-host.md),
> mit `--art prod`. Referenz: ADR-0013, ADR-0014, ADR-0015.

## 0 · Die Namen auf einen Blick

| Was | Name | Port | Erreichbar von |
|---|---|---|---|
| Kundenseiten | `<kunde>.mgmt.vitabrevis.ch` (z. B. `gmp.mgmt.vitabrevis.ch`) | 443 | Internet, **über die WAF** |
| Connector-Kanal (AD-Agent auf dem DC) | `connect.mgmt.vitabrevis.ch` | 46200 | Internet (Kunden-DCs), **an der WAF vorbei** |
| Konsole (Cockpit) | `https://mgmt.int.vitabrevis.ch:4444` (auch `konsole.mgmt.vitabrevis.ch`) | 4444 | **nur intern** (Verwaltungsnetz/VPN) |
| Server selbst | Hostname `mgmt`, FQDN `mgmt.int.vitabrevis.ch` | 22 | nur intern |

**Zertifikate:**

- **Kundenseiten:** gekauftes Wildcard **`*.mgmt.vitabrevis.ch`** (§3a), auf dem Server und auf der WAF.
  - `*.vitabrevis.ch` reicht nicht: ein Wildcard deckt nur **eine** Ebene ab. `mgmt.vitabrevis.ch` wäre gedeckt, `gmp.mgmt.vitabrevis.ch` nicht.
  - Let's Encrypt geht hinter der WAF nicht. Ohne WAF wäre es die Alternative (§9).
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
| `*.mgmt.vitabrevis.ch` | A | öffentliche Adresse der **WAF** |
| `connect.mgmt.vitabrevis.ch` | A | `<PUBLIC_IP>` (Firewall, **nicht** die WAF) |

Der Platzhalter deckt alle Kunden ab. Neue Kunden brauchen **keinen**
DNS-Eintrag mehr. `connect.` steht extra: der Agent meldet sich mit einem
Client-Zertifikat an (mTLS). Eine WAF, die TLS aufbricht, nimmt ihm das weg.

**Interner DNS** (Zone `int.vitabrevis.ch`, und eine Ausnahme für die Konsole):

| Eintrag | Typ | Ziel |
|---|---|---|
| `mgmt.int.vitabrevis.ch` | A | `<PRIVATE_IP>` |
| `konsole.mgmt.vitabrevis.ch` | A | `<PRIVATE_IP>` (optional; die Konsole ist auch unter `mgmt.int…` erreichbar) |
| `*.mgmt.vitabrevis.ch` | A | `<PRIVATE_IP>` (optional, gegen Hairpin-NAT für interne Aufrufe der Kundenseiten) |

**WAF** (für `*.mgmt.vitabrevis.ch`):

- Das Zertifikat `*.mgmt.vitabrevis.ch` mit Schlüssel einspielen, wenn die WAF TLS aufbricht.
- Backend `https://<PRIVATE_IP>:443`. Nicht HTTP: Caddy leitet HTTP auf HTTPS um, das gäbe eine Schleife.
- Den **Host-Header** (`gmp.mgmt.vitabrevis.ch`) unverändert weitergeben. Auch die **SNI** zum Backend sollte der Kundenname sein. An beidem erkennt die Plattform den Kunden.
- `X-Forwarded-For` mit der Client-Adresse setzen bzw. anhängen.
- Die Adressen, mit denen die WAF beim Server ankommt, braucht §5 (`--waf`).
- Für die Anmeldung über Entra muss die WAF Folgendes zulassen: Weiterleitungen mit `?code=…&state=…` auf `/api/auth/callback` und Cookies mit `SameSite=Lax`.

**Firewall, eingehend** (zu `<PRIVATE_IP>`):

| Port | Quelle | Wofür |
|---|---|---|
| TCP 443 | **nur die WAF** | Kundenseiten |
| TCP 46200 | Internet über `<PUBLIC_IP>` (oder nur die IPs der Kunden-DCs) | Connector-Kanal |
| TCP 4444 | **nur** Verwaltungsnetz/VPN | Konsole |
| TCP 22 | **nur** Verwaltungsnetz/VPN | SSH |

**Firewall, ausgehend** (TCP 443): `download.docker.com`,
`registry-1.docker.io` (+ `*.docker.io`, `production.cloudflare.docker.com`),
`ghcr.io`, `github.com` (+ `objects.githubusercontent.com`), `pypi.org`
(+ `files.pythonhosted.org`), `registry.npmjs.org`,
`login.microsoftonline.com`; dazu
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

## 3a · Wildcard-Zertifikat beantragen

Der Schlüssel entsteht auf dem Server, zur Zertifizierungsstelle geht nur der
Antrag. Das geht, sobald das Repository da ist (vor §4/§5):

```bash
cd /opt/magister
./scripts/plattform-aufbau.sh csr --domaene mgmt.vitabrevis.ch
```

Das Kommando legt zwei Dateien an:

- `plattform/kundenzertifikat/tenants-key.pem` (Schlüssel, nur für den Besitzer lesbar);
- `plattform/kundenzertifikat/tenants.csr`.

Der Antrag lautet auf `*.mgmt.vitabrevis.ch` und zusätzlich `mgmt.vitabrevis.ch`. Ein
zweiter Aufruf überschreibt den Schlüssel nie.

Das ausgestellte Zertifikat **samt Zwischenzertifikaten** als
`plattform/kundenzertifikat/tenants.pem` ablegen. Für die WAF exportiert man
dasselbe Paar, z. B. als PFX:

```bash
cd plattform/kundenzertifikat
openssl pkcs12 -export -in tenants.pem -inkey tenants-key.pem -out wildcard-mgmt.pfx
```

Stellt die IT das Zertifikat lieber selbst aus (eigener Schlüssel): dann
`tenants.pem` und `tenants-key.pem` (ohne Passwort) einfach dorthin legen.

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
./scripts/plattform-aufbau.sh up --art prod --tls eigen \
  --domaene mgmt.vitabrevis.ch \
  --bind <PRIVATE_IP> \
  --zusatzname mgmt.int.vitabrevis.ch \
  --waf "<WAF-Adressen, z. B. 10.20.30.0/28>"
```

`--waf` nennt die Adressen bzw. Netze, mit denen die WAF beim Server
ankommt. Mehrere trennt man mit Leerzeichen. Nur von dort glaubt Caddy dem
`X-Forwarded-For`, und die API sieht die echte Client-Adresse. Ohne die Angabe
stünde jeder Benutzer unter der IP der WAF im Audit-Log, und die
Anmeldesperre (20 Fehlversuche pro Minute und Adresse) träfe alle Kunden
gemeinsam.

`up` bricht ab, bevor etwas gebaut wird, wenn:

- `tenants.pem` oder `tenants-key.pem` fehlt;
- das Zertifikat `*.mgmt.vitabrevis.ch` nicht abdeckt.

Läuft es in weniger als 14 Tagen ab, gibt es einen Hinweis.

Die Angaben landen in `plattform/plattform.conf`. Jedes spätere `update`
liest sie von dort.

Was `--art prod` anders macht als der Testaufbau:

- **Keine Demo-Kunden.** Kunden legt man in der Konsole an (§6).
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
3. Prüfen: zuerst den Server direkt (an der WAF vorbei), dann **von aussen**
   über die WAF (Handy-Hotspot):

   ```bash
   # auf dem Server: Zertifikat und Antwort von Caddy
   curl -sI --resolve gmp.mgmt.vitabrevis.ch:443:<PRIVATE_IP> https://gmp.mgmt.vitabrevis.ch | head -1
   echo | openssl s_client -connect <PRIVATE_IP>:443 -servername gmp.mgmt.vitabrevis.ch 2>/dev/null \
     | openssl x509 -noout -subject -issuer -enddate
   # von aussen
   curl -sI https://gmp.mgmt.vitabrevis.ch | head -1
   ```

4. Kommt die echte Client-Adresse an? Im Portal unter Administration →
   Audit-Log muss bei der eigenen Anmeldung die öffentliche Adresse des
   Hotspots stehen, nicht die der WAF.

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

## 9 · Zertifikat erneuern — und die Alternative ohne WAF

**Erneuern** (jährlich, im Kalender eintragen):

1. Neuen Antrag stellen. Den alten Schlüssel vorher wegräumen, sonst zeigt
   `csr` den bestehenden Antrag:

   ```bash
   mv plattform/kundenzertifikat plattform/kundenzertifikat-$(date +%Y)
   ./scripts/plattform-aufbau.sh csr
   ```

2. Das neue `tenants.pem` ablegen und `./scripts/plattform-aufbau.sh up`
   ausführen. Die WAF bekommt dasselbe Paar.

**Ohne WAF** holt Caddy die Zertifikate selbst bei Let's Encrypt, eines je
Kunde, automatisch erneuert. Dafür muss Port 80 und 443 aus dem Internet
direkt auf den Server gehen:

```bash
./scripts/plattform-aufbau.sh up --tls letsencrypt --acme-mail <betrieb@vitabrevis.ch>
```

## 10 · Betrieb

```bash
cd /opt/magister
./scripts/plattform-aufbau.sh status     # Container und Zustand je Kunde
git pull && ./scripts/plattform-aufbau.sh update
./scripts/plattform-aufbau.sh konfig     # welche Angaben gelten
```

| Symptom | Ursache | Abhilfe |
|---|---|---|
| Kundenseite über die WAF: 502/504 | WAF spricht HTTP statt HTTPS mit dem Backend, oder Firewall lässt die WAF nicht auf 443 | WAF-Backend `https://<PRIVATE_IP>:443`; Firewall-Regel für die WAF-Adressen |
| Kundenseite: 404 `unknown_tenant` | Die WAF ersetzt den Host-Header durch ihre Backend-Adresse | Host-Header in der WAF unverändert durchreichen |
| Audit-Log zeigt nur die IP der WAF; Anmeldung „zu viele Versuche“ für alle | `--waf` fehlt oder enthält nicht die Adressen, mit denen die WAF ankommt | `up --waf "…"` mit den richtigen Netzen |
| Entra-Anmeldung endet mit `oidc_state_mismatch` / `oidc_callback_invalid` | Die WAF verwirft Cookies oder Query-Parameter auf `/api/auth/callback` | Ausnahme in der WAF für `/api/auth/*` |
| `up`: „deckt *.mgmt.vitabrevis.ch nicht ab“ | Falsches Zertifikat abgelegt (z. B. `*.vitabrevis.ch`) | Das Zertifikat aus dem Antrag von §3a ablegen |
| Kundenseite 503 „maintenance“, `status`: keine Kunden | Datenebene erreicht die Konsole nicht | `docker exec magister-magister-api-1 getent hosts konsole.mgmt.vitabrevis.ch` muss `<PRIVATE_IP>` zeigen; sonst `up` erneut |
| Konsole 421 | Aufruf unter einem Namen, der nicht im Zertifikat steht | `https://mgmt.int.vitabrevis.ch:4444` verwenden |
| Agent: `CERTIFICATE_VERIFY_FAILED` | `root.pem` fehlt beim `enroll` oder ein Proxy bricht TLS auf | `enroll --ca …\root.pem`; 46200 am Proxy vorbei |
