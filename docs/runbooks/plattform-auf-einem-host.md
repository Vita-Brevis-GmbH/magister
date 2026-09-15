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

Voreingestellt ist die Domäne `dev-mgmt.int.vitabrevis.ch`; in Produktion:

```bash
./scripts/plattform-aufbau.sh up --domaene mgmt.vitabrevis.ch --bind 10.0.0.5 --ziehen
```

`--ziehen` holt die Abbilder aus GHCR statt sie zu bauen. Ohne die Option
werden sie aus dem ausgecheckten Stand gebaut — genau dafür gibt es die
Option, ein Stand ohne Abbild lässt sich sonst nicht ausprobieren.

Was entsteht:

| Schritt | Ergebnis |
|---|---|
| Plattform-CA | Wurzel, zwei Zwischenstellen, Server- und Client-Zertifikate in `plattform/certs/` |
| Umgebung | `cockpit/deploy/.env` und `deploy/compose/.env`, beide `0600` |
| Netz | `magister-plattform`, damit die Konsole den Magister-Cluster erreicht |
| Konsolen-Stack | Postgres, API, Caddy auf `<bind>:4444` mit Client-Zertifikat |
| Datenebenen-Stack | Postgres, API, Web, Caddy auf 443 nach Hostname getrennt, Sicherungs-Container |
| Zwei Kunden | über die API der Konsole, durch den Verwaltungs-Listener, wie ein Operator es täte |

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
echo "127.0.0.1 konsole.dev-mgmt.int.vitabrevis.ch thun.dev-mgmt.int.vitabrevis.ch bern.dev-mgmt.int.vitabrevis.ch" >> /etc/hosts
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

## 6 · Anhalten und Abbauen

```bash
./scripts/plattform-aufbau.sh down    # Container anhalten, Daten behalten
./scripts/plattform-aufbau.sh purge   # Container, Volumes, Netz, Zertifikate und .env löschen
```

`purge` löscht Kundendaten. Auf dem Produktionsserver hat dieser Befehl
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
