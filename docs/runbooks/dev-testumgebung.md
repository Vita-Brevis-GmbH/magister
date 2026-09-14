# Runbook · Entwicklungsumgebung und Prüfplan

> Die ganze Plattform auf einer Maschine: Konsole, Anwendungsserver, **zwei**
> Kunden in getrennten Schemas, Test-CA, beide Listener. Dazu ein Prüfplan mit
> den Handgriffen, die in Produktion zählen.
> Skript: [`scripts/dev-umgebung.sh`](../../scripts/dev-umgebung.sh).
> Status: **gebaut und durchlaufen** (2026-09-14).

## 1 · Wofür das gut ist — und wofür nicht

Diese Umgebung ist da, um **die Plattform** zu prüfen: Mandantentrennung,
Versions-Schranke, Lastgrenzen, Migrationswelle, Umzug, Flotte, Operator-Zugriff,
die Überwachungssonden. Wer nur die Fachanwendung mit einem Mandanten sehen
will, ist mit `scripts/install-magister.sh --mode dev` schneller — die kennt
aber weder Konsole noch zweiten Kunden, also genau das nicht, worauf es beim
Aufbau der Plattform ankommt.

**Zwei Kunden, nicht einer.** Ein Mandant versteckt fast jeden
Mandantenfehler: der Fan-out, der stumm nur einen bedient; der fehlende
Kundenschlüssel, der bei einem Mandanten durch die Vorgabe gedeckt ist; der
Scope, der nie greift, weil alles im selben Schema liegt. Drei solche Fehler
sind in diesem Projekt genau so gefunden worden.

**Was hier NICHT geprüft wird**, und was das für den Prod-Aufbau heisst:

| Fehlt | Folge |
|---|---|
| Ein echtes Active Directory (es läuft der ldap3-Mock) | Bind-Modus, GSSAPI, Delegierung und Passwort-Richtlinien bleiben ungeprüft. Ein Test-DC lässt sich anhängen (§7). |
| Ein echter Connector-Agent auf einem Windows-Server | Der Kanal ist geprüft, der Dienst und das MSI nicht. |
| Die WAF | TLS-Terminierung vor den beiden mTLS-Ports ist der Fall, der in Produktion beisst — hier gibt es sie nicht. |
| Die echte Plattform-CA | Hier steht eine Test-CA mit Schlüsseln ohne Passwort in `dev/certs/`. Sie darf **nie** ausserhalb dieses Verzeichnisses eine Rolle spielen. |
| PITR / WAL-Archivierung | Nur die logischen Dumps sind prüfbar. |

## 2 · Voraussetzungen

Debian/Ubuntu oder macOS, dazu:

```bash
uv          # Python-Umgebungen        https://docs.astral.sh/uv/
openssl     # Test-CA
psql        # Postgres-Client
postgres 16 # erreichbar, mit einem Benutzer, der CREATEDB und CREATEROLE darf
caddy       # optional: die beiden TLS-Listener
age         # optional: Sicherungen und Vor-Migrations-Dumps
pnpm        # optional: die beiden Oberflächen bauen
```

Ohne `caddy` läuft alles, nur ohne TLS und ohne Client-Zertifikate — dann
fehlt genau der Teil, der in Produktion die Konsole schützt. Für einen
ernsthaften Durchgang lohnt es sich.

## 3 · Aufbauen

```bash
DEV_PG_USER=postgres DEV_PG_PASSWORD=… ./scripts/dev-umgebung.sh up
```

Das Skript legt an: zwei Datenbanken, eine Test-CA (Wurzel, zwei
Zwischenstellen, Server-, Operator- und Monitor-Zertifikat, ein
age-Schlüsselpaar), zwei Umgebungsdateien mit frischen Geheimnissen, das
Konsolen-Schema, **zwei Kunden über die echte Bereitstellung** (Rolle, Schema,
Migration, Kundenschlüssel, Freischalten), Demodaten je Kunde, und startet
Konsole, Anwendungsserver und Caddy.

Danach:

| Was | Wo |
|---|---|
| Konsole (Oberfläche + API) | `https://console.mgmt.vitabrevis.dev:4444` — Client-Zertifikat Pflicht |
| Kunde 1 | `https://thun.mgmt.vitabrevis.dev:8443` |
| Kunde 2 | `https://bern.mgmt.vitabrevis.dev:8443` |
| Konsolen-API direkt | `http://127.0.0.1:8099` (ohne Caddy, ohne Zertifikat) |
| Anwendungsserver direkt | `http://127.0.0.1:8000` |
| Geheimnisse | `dev/env.console`, `dev/env.dataplane` |
| Protokolle | `dev/logs/*.log` |

Zwei Handgriffe bleiben:

```bash
# Namen auflösbar machen (einmalig, als root)
echo "127.0.0.1 console.mgmt.vitabrevis.dev thun.mgmt.vitabrevis.dev bern.mgmt.vitabrevis.dev" \
  | sudo tee -a /etc/hosts

# Oberflächen bauen
(cd cockpit/web && pnpm install && pnpm build)
(cd apps/web    && pnpm install && pnpm build)
```

Zustand jederzeit:

```bash
./scripts/dev-umgebung.sh status
#   console  läuft (PID 1494)
#   api      läuft (PID 1538)
#   caddy    läuft (PID 1720)
#   thun     Stufe 1 (warning) — ad_sync: noch nie gelaufen
#   bern     Stufe 1 (warning) — ad_sync: noch nie gelaufen
```

## 4 · Zugang zur Konsole

**Als Operator** (der reguläre Weg, ADR-0020): erst die Person eintragen, dann
das Zertifikat in den Browser, dann beim ersten Anmelden den zweiten Faktor
einrichten.

```bash
source dev/env.console
(cd cockpit/api && uv run python -m cockpit_api.cli.add_operator \
   --upn dev@vitabrevis.dev --name "Dev Operator" --cert ../../dev/certs/operator.pem)

# Zertifikat für den Browser
openssl pkcs12 -export -inkey dev/certs/operator-key.pem -in dev/certs/operator.pem \
  -certfile dev/certs/platform-ca.pem -out dev/certs/operator.p12 -passout pass:dev
```

Danach `https://console.mgmt.vitabrevis.dev:4444` öffnen, das Zertifikat
auswählen, QR-Code scannen, Code eingeben. Prüfen ohne Browser:

```bash
curl -sk --cert dev/certs/operator.pem --key dev/certs/operator-key.pem \
  https://console.mgmt.vitabrevis.dev:4444/api/auth/console/whoami
# {"stage":"enrolment_required","upn":"dev@vitabrevis.dev",...}

curl -sk https://console.mgmt.vitabrevis.dev:4444/api/auth/console/whoami
# schlägt im Handshake fehl — ohne Zertifikat gibt es keine HTTP-Antwort
```

> Hinter einem Unternehmens-Proxy scheitert das lautlos: ein `CONNECT` durch
> einen Proxy nimmt das Client-Zertifikat nicht mit, und die Antwort ist leer
> statt fehlerhaft. `curl --noproxy '*'` oder den Host in `no_proxy`.

**Als Notzugang** (wenn noch kein Operator existiert): der Bootstrap-Token aus
`dev/env.console`, in der Oberfläche unter „Notzugang mit Bootstrap-Token".
Er schreibt im Protokoll `bootstrap-token` statt eines Namens — genau wie in
Produktion.

## 5 · Prüfplan

Zwölf Handgriffe, jeder in ein paar Minuten. Der Wert steckt in den negativen
Fällen: eine Prüfung, die nur den Erfolgsweg zeigt, hat nichts gezeigt.

### 5.1 Die Trennung hält

```bash
source dev/env.dataplane
# psql kennt den SQLAlchemy-Treiber im DSN nicht — er muss raus:
THUN="${MAGISTER_TENANT_DSN_TENANT_THUN/+asyncpg/}"

psql "$THUN" -c "select current_user, current_schema()"
psql "$THUN" -c "select count(*) from t_thun.classes"     #  2 (Demodaten)

# Und die Rolle des einen kommt nicht in das Schema des anderen:
psql "$THUN" -c "select count(*) from t_bern.classes"
#   FEHLER: keine Berechtigung für Schema t_bern     <-- DAS ist das Ergebnis
```

Die Trennung hängt an dieser Fehlermeldung und nicht an Anwendungslogik
(ADR-0013 D1). Wer sie prüfen will, muss sie an der Datenbank sehen — ein
Test über die API prüft nur, dass die Anwendung richtig filtert.

In der Oberfläche: beide Kundenseiten öffnen, in beiden eine Klasse anlegen,
und nachsehen, dass sie in der jeweils anderen nicht auftaucht.

### 5.2 Die Versions-Schranke greift

```bash
# Schemastand des Kunden künstlich zurücksetzen (nur hier, nie in Produktion):
source dev/env.console
psql "${COCKPIT_DATABASE_URL/+asyncpg/}" \
  -c "update tenants set schema_version='0001_alt' where slug='thun'"
# Bis zu einer Minute warten (die Datenebene lädt die Registry nach), dann:
curl -sk https://thun.mgmt.vitabrevis.dev:8443/api/me   # 503 maintenance
curl -sk -H "X-Magister-Health: $MAGISTER_HEALTH_TOKEN" \
  https://thun.mgmt.vitabrevis.dev:8443/healthz/stack | jq '.status, .checks[2]'
#   2  und „Schema steht auf 0001_alt, der Code auf 0046_…"
```

Zurücksetzen: denselben `update` mit dem echten Kopfstand.

### 5.3 Lastgrenzen wirken in Postgres

In der Konsole beim Kunden „Lastgrenzen" setzen (z.B. 15000 ms, 60
Verbindungen), dann gegenlesen — nicht in der Konsole, sondern dort, wo sie
gelten:

```bash
psql -d magister_dev -c \
  "select rolname, rolconnlimit, rolconfig from pg_roles where rolname='r_thun'"
```

### 5.4 Migrationswelle mit Kanarienvogel und verschlüsseltem Dump

```bash
cd apps/api && source ../../dev/env.dataplane
uv run ../../scripts/magister-cli tenants list
uv run ../../scripts/magister-cli tenants migrate \
  --canary thun --canary-only --dump-dir ../../dev/dumps
```

Erwartet: ein Dump je Kunde (`*.dump.age`), danach Halt mit „hier ist
Schluss". Der Dump ist **verschlüsselt** — nachweisbar:

```bash
head -c 20 dev/dumps/thun-*.dump.age    # "age-encryption.org/v1"
age -d -i dev/certs/backup-age.key dev/dumps/thun-*.dump.age | head -c 40
```

Und der negative Fall, der die harte Regel trägt:

```bash
MAGISTER_BACKUP_AGE_RECIPIENT= uv run ../../scripts/magister-cli tenants migrate
#   bricht ab, bevor irgendetwas passiert
```

### 5.5 Der Kunde sieht, dass sein Schema angefasst wurde

Nach 5.4 im Protokoll des Kunden nachsehen (Oberfläche → Protokoll, oder über
die API): ein Ereignis `schema_migrated` mit Vorher- und Nachher-Revision.
Und in der Konsole steht beim Kunden jetzt „gemeldet <Zeitpunkt>" statt
„erwartet, nie gemeldet".

### 5.6 Umzug auf eine andere Ablage

In der Konsole: Kunde sperren → „Ablage umstellen" erscheint → Verweis auf
`tenant_thun_c2`, Trennung `cluster`, Haken setzen, umstellen. Erwartet: bei
**aktivem** Kunden steht statt des Formulars die Begründung, warum erst
gesperrt werden muss.

### 5.7 Flotte und Exit-Code

```bash
source dev/env.console
(cd cockpit/api && uv run python -m cockpit_api.cli.fleet_check); echo "Exit: $?"
#   0 kritisch, 2 Warnung(en).  … Exit: 1
```

Zwei aktive Kunden ohne Agenten sind zu Recht eine Warnung. In der Konsole
zeigt der Reiter „Flotte" dieselben Befunde.

### 5.8 Die Sonden für PRTG

```bash
source dev/env.dataplane
curl -sk -H "X-Magister-Health: $MAGISTER_HEALTH_TOKEN" \
  https://thun.mgmt.vitabrevis.dev:8443/healthz/stack | jq
curl -sk https://thun.mgmt.vitabrevis.dev:8443/healthz/stack -o /dev/null -w "%{http_code}\n"
#   404 — ohne Token gibt es die Route nicht
curl -sk --cert dev/certs/prtg-monitor.pem --key dev/certs/prtg-monitor-key.pem \
  https://console.mgmt.vitabrevis.dev:4444/api/health/stack | jq .status
```

Einzelheiten: [ueberwachung-prtg.md](ueberwachung-prtg.md).

### 5.9 Operator-Zugriff auf Kundendaten

In der Konsole beim Kunden → Reiter „Zugriff" → Einlöseschein mit Grund
ausstellen. Erwartet: ohne Grund (mind. zehn Zeichen) kein Schein; der Schein
gilt sechzig Sekunden; nach dem Einlösen steht im Kundenprotokoll
`operator_access_started` **mit Namen**, und jeder angemeldete Benutzer des
Kunden sieht einen Hinweisbalken. Zweimal einlösen geht nicht.

### 5.10 Sicherung und Wiederherstellung

In der Konsole beim Kunden → „Sicherungen" → Sicherung auslösen; danach
prüfen, dass die Datei in `dev/backups/` liegt und mit `age` beginnt. Die
Wiederherstellung in ein Prüfschema steht in
[sicherung-wiederherstellung.md](sicherung-wiederherstellung.md).

### 5.11 AD-Abgleich

Mit dem Mock läuft der Abgleich, findet aber nur, was jemand in die
Mock-Verbindung gelegt hat — für den Weg (Fan-out je Kunde, inkrementell,
Audit) reicht das:

```bash
tail -f dev/logs/api.log | grep -i "abgleich\|ad_sync"
```

Erwartet: **beide** Kunden kommen dran, versetzt, jeder mit eigener Sitzung.
Ein Kunde mit kaputtem AD hält den anderen nicht auf — nachstellen, indem man
in `dev/env.dataplane` die Suchbasis eines Kunden leert und den Prozess neu
startet.

### 5.12 Die Konsolenoberfläche

Kunden anlegen, sperren, entsperren, Rollenpasswort drehen, Vorlagen
schreiben und zuweisen, Systemeinstellungen setzen und beim Kunden
nachsehen, Kündigung anstossen. Der Reiter „Flotte" und die Lastgrenzen sind
oben schon abgedeckt.

## 6 · Abbauen

```bash
./scripts/dev-umgebung.sh down    # Prozesse beenden, Daten behalten
./scripts/dev-umgebung.sh purge   # Datenbanken, Rollen und dev/ löschen
```

`dev/` steht in `.gitignore`: darin liegen echte Geheimnisse und Kundendumps.

## 7 · Mit einem echten Test-DC

Wer eine Test-Domäne hat, ersetzt in `dev/env.dataplane`:

```bash
export MAGISTER_AD_USE_MOCK="0"
export MAGISTER_AD_DCS="dc1.test.local"
export MAGISTER_AD_BIND_MODE="simple"        # oder gssapi
export MAGISTER_AD_BIND_DN="CN=svc-magister,OU=Dienste,DC=test,DC=local"
export MAGISTER_AD_BIND_PASSWORD="…"
export MAGISTER_AD_USERS_SEARCH_BASE="OU=Benutzer,DC=test,DC=local"
```

Damit werden Bind, Suche, Passwort-Reset und der Abgleich echt. Der
Connector-Weg (Agent statt direktes LDAP) verlangt zusätzlich einen
angemeldeten Agenten — dafür `MAGISTER_AD_CONNECTOR_ENABLED=1` lassen und den
Agenten nach [kunden-onboarding.md](kunden-onboarding.md) §3 anmelden; das
Einmal-Token stellt die Konsole aus.
