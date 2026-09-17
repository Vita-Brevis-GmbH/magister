# Runbook · Die Plattform auf einem Host

> Die gehostete Magister-Plattform — Konsole und Datenebene, beide als
> Container, mit den Compose-Dateien, die auch in Produktion laufen.
> Referenz: [ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md),
> [ADR-0015](../adr/0015-konsole-management-listener.md),
> [ADR-0020](../adr/0020-konsolen-anmeldung.md),
> [ADR-0021](../adr/0021-betrieb-im-grossen.md).

Dieses Runbook beschreibt **einen** Aufbau, der zweimal verwendet wird: auf
einer Testmaschine und auf dem Produktionsserver. Es gibt keinen zweiten
Ablauf — was hier scheitert, scheitert dort auch, und das ist der Zweck.

## 0 · Der Unterschied zur Entwicklungsumgebung

`scripts/dev-umgebung.sh` startet die Dienste als nackte Prozesse, damit man
mit einem Breakpoint hineinkommt. Das ist zum Programmieren richtig und zum
Prüfen des Betriebs falsch: Container, Netze, Volumes, Caddy und die
Pflichtwerte der Compose-Dateien sind genau die Stellen, an denen ein
Aufbau scheitert.

`scripts/plattform-aufbau.sh` macht deshalb das andere: dieselben Container
wie in Produktion, dieselben Compose-Dateien, dasselbe Caddy, dieselben
Netze.

## 1 · Was die Maschine braucht

```bash
docker + compose-Plugin   # der Rest läuft in Containern
openssl                   # Zertifikate
pnpm                      # die Konsolen-Oberfläche (sonst antwortet der
                          # Listener nur auf /api/*)
age                       # Sicherungen (ADR-0016 D9)
```

Ports: **443** und **80** für die Kundenseiten, **4444** für die Konsole
(nur auf der Verwaltungsadresse), **46200** für den Connector-Kanal.

## 2 · Aufbauen

```bash
cd /opt/magister
./scripts/plattform-aufbau.sh up
```

Beim ersten Mal fragt das Skript drei Dinge und schreibt sie nach
`plattform/plattform.conf`:

| Angabe | Was sie bedeutet | Vorschlag |
|---|---|---|
| Domäne | die Ebene, unter der die Kundennamen liegen | `dev-mgmt.int.vitabrevis.ch` |
| Verwaltungsadresse | die eine Adresse, auf der die Konsole lauscht (nie `0.0.0.0`) | die Adresse aus der Routing-Tabelle |
| Zweiter Name | der FQDN dieser Maschine; er kommt in das Zertifikat **und** in den Site-Block von Caddy | `hostname -f` |

**Danach werden sie nie wieder gefragt** — auch nicht beim Update. Wer sie
gleich mitgeben will (oder keine Rückfrage haben kann, etwa in einem
Playbook):

```bash
./scripts/plattform-aufbau.sh up --domaene mgmt.vitabrevis.ch \
  --bind 10.0.0.5 --zusatzname srv01.int.vitabrevis.ch --ziehen
```

Was gerade gilt, sagt:

```bash
./scripts/plattform-aufbau.sh konfig
```

`--ziehen` holt die Abbilder aus GHCR statt sie zu bauen. Ohne die Option
werden sie aus dem ausgecheckten Stand gebaut — genau dafür gibt es die
Option, ein Stand ohne Abbild lässt sich sonst nicht ausprobieren.

### 2.1 Die Rangfolge der Angaben

Von stark nach schwach: **Option** auf der Kommandozeile → **Umgebungs-
variable** (`PLATTFORM_BIND=…`) → **gespeicherte Konfiguration** →
**Rückfrage** bei der Erstinstallation → **Vorgabe**. Die ersten beiden
werden in die Konfiguration zurückgeschrieben, aber nur bei `up`; ein
`konfig --bind …` oder `status --bind …` gilt nur für diesen einen Aufruf.

Eine Vorgabe überschreibt **nie** einen gespeicherten Wert. Das ist die Regel,
an der es zweimal gescheitert ist: `--bind` und `--zusatzname` waren blosse
Optionen mit Vorgabewert, ein `up` ohne Optionen setzte die Bindung deshalb
auf `127.0.0.1` zurück — und die Konsole war nach jedem Update wieder
unerreichbar. Gemessen wird das jetzt in
`scripts/tests/plattform-konfig.test.sh` (läuft ohne Docker).

Was entsteht:

| Schritt | Ergebnis |
|---|---|
| Plattform-CA | Wurzel, zwei Zwischenstellen, Server- und Client-Zertifikate in `plattform/certs/` |
| Umgebung | `cockpit/deploy/.env` und `deploy/compose/.env`, beide `0600` |
| Netz | `magister-plattform`, damit die Konsole den Magister-Cluster erreicht |
| Konsolen-Stack | Postgres, API, Caddy auf `<bind>:4444` mit Client-Zertifikat |
| Datenebenen-Stack | Postgres, API, Web, Caddy auf 443 nach Hostname getrennt, Sicherungs-Container |
| Zwei Kunden | über die API der Konsole, durch den Verwaltungs-Listener, wie ein Operator es täte |

### 2.2 Nach einem `git pull`

```bash
git pull && ./scripts/plattform-aufbau.sh update   # `up` tut dasselbe
```

`up` ist der Weg für ein Update, nicht nur für den ersten Aufbau — `update`
ist derselbe Befehl unter dem Namen, unter dem man ihn sucht. Ohne Optionen
aufrufen: die Angaben aus der Erstinstallation gelten weiter.

Was ein Update anfasst:

| | |
|---|---|
| Abbilder | neu gebaut (`--build`) resp. gezogen (`--ziehen`) |
| Oberfläche | neu gebaut, sobald `cockpit/web/src` neuer ist als `cockpit/web/dist` |
| Caddy | immer neu erzeugt (die Konfiguration ist eine eingehängte Datei) |
| `.env` beider Stacks | Namen und Adressen nachgeführt, Geheimnisse unangetastet |
| Zertifikate | neu ausgestellt, wenn ein Name fehlt; sonst unangetastet |
| Datenbank | `alembic upgrade head` in der Konsole |

Das war eine Zeitlang nicht so: `up` stieg aus, sobald `dist/index.html`
überhaupt existierte, und meldete „steht bereits". Eine neu gebaute Ansicht
war nach dem Update im Browser nicht da, obwohl das Skript Vollzug meldete.
Liegt die Erkennung einmal daneben, hilft `up --ui-neu` — das baut die
Oberfläche in jedem Fall.

Und wenn die Seite danach immer noch alt aussieht: einmal hart neu laden
(Strg+Umschalt+R). Die Namen der JS-Dateien tragen eine Prüfsumme, `index.html`
nicht.

**In Produktion anders — und nur das:**

1. Die Plattform-CA entsteht in der Zeremonie auf dem Offline-Rechner
   ([platform-ca.md](platform-ca.md)), nicht auf dem Server. Die Dateien
   werden nach `plattform/certs/` gelegt, bevor `up` läuft; das Skript lässt
   eine vorhandene CA unangetastet.
2. Die Abbilder kommen aus GHCR (`--ziehen`).

## 3 · Die zwei Vertrauenslisten

Am Konsolen-Listener hängen zwei Dateien, und sie beantworten verschiedene
Fragen:

| Datei | Frage | Inhalt |
|---|---|---|
| `platform-ca.pem` | Ist dieser **Server** echt? | Wurzel + Operator-Zwischenstelle |
| `operator-ca.pem` | Darf dieser **Client** anklopfen? | **nur** die Operator-Zwischenstelle |

Warum nicht eine Datei für beides: was im Client-Pool liegt, ist ein
Vertrauensanker. Mit der Wurzel darin gälte auch ein Zertifikat aus dem
Connector-Zweig — und davon hat jeder Kunde eines auf seinem Agenten-Server
im eigenen Netz. Gemessen (`dev-pruefen.sh T12`): mit Wurzel im Pool kommt
ein Agentenzertifikat durch den Handshake, mit nur der Operator-Zwischenstelle
nicht. Der Agenten-Listener auf 46200 kennt aus demselben Grund **nur** den
Connector-Zweig.

## 4 · Namen

In Produktion macht das der DNS. Auf einer Testmaschine reicht die Datei:

```bash
# Die Adresse ist die aus `konfig` (PLATTFORM_BIND), nicht zwingend 127.0.0.1:
echo "172.25.12.10 konsole.dev-mgmt.int.vitabrevis.ch thun.dev-mgmt.int.vitabrevis.ch bern.dev-mgmt.int.vitabrevis.ch" >> /etc/hosts
```

**Ein Platzhalter-Zertifikat gilt für genau eine Ebene.**
`*.dev-mgmt.int.vitabrevis.ch` deckt `thun.dev-mgmt.int.vitabrevis.ch` ab,
aber nichts darunter. Beim Bestellen des echten Zertifikats mitbestellen
(siehe [console-listener.md](console-listener.md) §2.1a).

## 5 · Prüfen

```bash
./scripts/plattform-aufbau.sh status
```

zeigt beide Stacks und die Stufe je Kunde (0/1/2 wie in PRTG, ADR-0021 D6).

Von Hand die drei Aussagen, die den Aufbau tragen:

```bash
# 1. Jeder Hostname landet bei seinem Kunden — und ein fremder bei niemandem.
TOKEN=$(grep -oP '(?<=^MAGISTER_HEALTH_TOKEN=).*' deploy/compose/.env)
for name in thun bern; do
  curl -sk --resolve $name.dev-mgmt.int.vitabrevis.ch:443:127.0.0.1 \
    -H "X-Magister-Health: $TOKEN" \
    https://$name.dev-mgmt.int.vitabrevis.ch/healthz/stack | head -c 200; echo
done

# 2. Die Trennung hält an Postgres: die Rolle des einen kommt nicht ins
#    Schema des anderen.
docker compose --project-directory deploy/compose exec -T postgres \
  psql -U r_thun -d magister -c 'select count(*) from t_bern.classes'
#    Erwartet: permission denied for schema t_bern

# 3. Die Konsole ist ohne Client-Zertifikat nicht erreichbar.
curl -sk --resolve konsole.dev-mgmt.int.vitabrevis.ch:4444:127.0.0.1 \
  https://konsole.dev-mgmt.int.vitabrevis.ch:4444/api/health
#    Erwartet: der Handshake scheitert (curl 35/58), keine Antwort
```

**Der vollständige Prüfer läuft heute gegen die Prozess-Umgebung**
(`dev-umgebung.sh`), nicht gegen diesen Container-Aufbau: seine zwölf
Prüfungen greifen mit `psql` und `magister-cli` direkt auf Rollen, Dumps und
die Konsolen-Datenbank zu, und beide liegen hier in Containern ohne
Host-Port. Die Umstellung ist der nächste Schritt und braucht einen
laufenden Aufbau als Gegenüber — vorher wäre sie geraten statt geprüft.

Was auch danach eine Person verlangt, mit Zertifikat und TOTP: die Anmeldung
an der Konsole, Operator-Zugriff auf Kundendaten, Sicherung und
Wiederherstellung über die Oberfläche. Diese Schritte stehen in
[dev-testumgebung.md](dev-testumgebung.md) §5.9–§5.12 und gelten unverändert.

## 5a · Operatoren und TOTP

Beide Werkzeuge laufen **in** der Konsole, und beide gehen über das Skript —
nicht über `docker compose exec` von Hand:

```bash
./scripts/plattform-aufbau.sh operator --upn … --name "…" --set-password
./scripts/plattform-aufbau.sh operator --upn … --reset-mfa
./scripts/plattform-aufbau.sh totp --upn … --code 123456
```

Der Grund ist eine Falle, die einen Abend gekostet hat: `exec api python -m
…` führt den Code aus, der beim **Bauen** in das Abbild kopiert wurde. Ein
`git pull` ändert daran nichts — das Werkzeug im Container ist dann älter
als das Repository, und ein neues Argument existiert dort nicht
(„unrecognized arguments: --reset-mfa"). Die beiden Befehle oben bauen das
Abbild vorher neu.

`totp` ordnet einen abgewiesenen Code ein: passt er mit Versatz, geht eine
Uhr falsch; passt er zu keinem Zeitschritt in ±5 Minuten, hält die App ein
anderes Geheimnis als die Datenbank — dann `--reset-mfa` und neu
einrichten.

## 5b · Agentenpakete bereitstellen

Die Konsole bietet die gebauten Pakete des Connector-Agenten zum Herunterladen
an (*Kunde → AD-Connector → „Agent herunterladen"*). Sie **baut nichts**: sie
liest ein Verzeichnis, das der Aufbau anlegt und schreibgeschützt einhängt.

```bash
./scripts/agentenpakete.sh holen    # MSI + .deb aus der CI
./scripts/agentenpakete.sh bauen    # nur das .deb, hier auf der Maschine
./scripts/agentenpakete.sh zeigen   # was liegt da, mit Prüfsumme
```

Die Konsole sieht neue Dateien sofort; ein Neustart ist nicht nötig. Ist das
Verzeichnis leer, sagt die Oberfläche das — und nicht „es gibt kein Paket".

**Das MSI kann diese Maschine nicht bauen.** PyInstaller friert die Laufzeit
ein, auf der es selbst läuft; ein Windows-Programm entsteht nur unter Windows.
Deshalb baut es `agent-ci.yml` auf einem Windows-Runner, und `holen` lädt das
Ergebnis herunter. Was hier entstünde, wäre der Platzhalter aus
`build-msi.sh --stub` — installierbar, aber ohne Inhalt, und deshalb trägt er
STUB im Namen.

`holen` braucht ein Token mit `actions:read` in `GITHUB_TOKEN` oder in
`~/.magister/github-token` (0600). Es geht über `curl --config` in die
Anfrage und steht damit weder in der Prozessliste noch in der History. Von
einem anderen Zweig als `main`:

```bash
AGENT_CI_ZWEIG=claude/mein-zweig ./scripts/agentenpakete.sh holen
```

Wer kein Token auf dem Server will, holt die Datei einmal von Hand: GitHub →
Actions → *agent-ci* → letzter grüner Lauf → Artefakte
`magister-connector-msi` und `magister-connector-deb`, entpacken, in das
Verzeichnis legen. Artefakte verfallen (Vorgabe 90 Tage, das Payload nach 7);
ist keines mehr da, den Workflow neu starten (*Run workflow*).

Die heruntergeladenen Dateien bekommen den Commit-Stand in den Namen
(`…-a1b2c3d4.msi`). Sonst liegen dort irgendwann zwei Dateien, die gleich
heissen und verschieden sind, und niemand weiss, welche der Kunde bekommen
hat.

Zwei Dinge, die die Prüfsumme in der Liste **nicht** ist: sie ist kein
Herkunftsnachweis (dafür die Paketsignatur, Entscheid E18), und sie ersetzt
das apt-Repository nicht (siehe `agent/packaging/apt/`). Sie beantwortet die
eine Frage, die beim Onboarding am Telefon steht: „ist die Datei, die ich
hier habe, dieselbe wie bei euch?"

## 6 · Anhalten und Abbauen

```bash
./scripts/plattform-aufbau.sh down    # Container anhalten, Daten behalten
./scripts/plattform-aufbau.sh purge   # Container, Volumes, Netz, Zertifikate und .env löschen
./scripts/plattform-aufbau.sh purge --auch-konfiguration   # zusätzlich plattform.conf
```

`purge` lässt `plattform/plattform.conf` stehen: sie enthält keine
Geheimnisse und keine Kundendaten, nur die drei Antworten aus der
Erstinstallation. Der Wiederaufbau trifft damit dieselbe Maschine unter
denselben Namen — statt dass jemand sie erneut tippt und irgendwann anders
tippt.

`purge` löscht Kundendaten — und mit dem Plattform-Verzeichnis auch die
abgelegten Agentenpakete. Auf dem Produktionsserver hat dieser Befehl
nichts zu suchen.

## 7 · Was hier auffällt, fällt in Produktion nicht mehr auf

Beim ersten Aufbau nach diesem Runbook kamen vier Dinge zutage, die alle
erst beim ersten Kunden sichtbar geworden wären:

* Die Konsole braucht das Alembic-Verzeichnis der Datenebene **im
  Container** (`docker-compose.plattform.yml` hängt es ein). Ohne das
  bleibt jeder Kunde mit Rolle und Schema, aber ohne Tabellen stehen.
* Beide Stacks haben einen Dienst namens `postgres`. Ohne eigenen Namen im
  gemeinsamen Netz legte die Konsole die Kundenschemas in ihrer eigenen
  Datenbank an.
* Der Verwaltungszugang braucht kein Superuser zu sein, aber seit Postgres
  16 muss er sich das Recht, eine angelegte Mandantenrolle anzunehmen,
  ausdrücklich verschaffen (behoben in `services/provisioning.py`).
* Der Client-Trust-Pool des Konsolen-Listeners darf die Wurzel nicht
  enthalten (Abschnitt 3).
