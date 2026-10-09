# Runbook · Überwachung mit PRTG

> Was überwacht wird, womit, und was jeder Alarm heisst.
> Referenz: [ADR-0021](../adr/0021-betrieb-im-grossen.md) D6 (alarmieren ist
> Aufgabe der Überwachung, nicht von Magister),
> [ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md) D7 (Versions-Schranke).
> Status: **gebaut, in PRTG noch einzurichten.**

## 1 · Der Grundsatz

Magister alarmiert nicht selbst. Kein SMTP, keine Webhooks, keine zweite
Alarmierung neben der, die im Betrieb schon läuft — die wäre die, die niemand
liest. Magister liefert **Zahlen**, PRTG entscheidet, wann es klingelt.

Überall dieselbe Skala, damit niemand zwei Zahlenwelten unterscheiden muss:

| Wert | Bedeutung | In PRTG |
|---|---|---|
| `0` | in Ordnung | grün |
| `1` | jemand soll hinsehen | gelb (Warnung) |
| `2` | jemand soll **heute** hinsehen | rot (Fehler) |

## 2 · Vier Sensoren

| # | Was | Wo | Sensortyp |
|---|---|---|---|
| 1 | Lebt die Kundenseite? | `https://<kunde>.mgmt.vitabrevis.ch/healthz` | HTTP |
| 2 | Ist der Stack dieser Seite gesund? | `https://<kunde>.mgmt.vitabrevis.ch/healthz/stack` | HTTP XML/REST Value |
| 3 | Ist die Konsole gesund? | `https://console.mgmt.vitabrevis.ch:4444/api/health/stack` | HTTP XML/REST Value |
| 4 | Ist die Flotte gesund? | `python -m cockpit_api.cli.fleet_check` auf dem Konsolen-Host | SSH Script / EXE |

Sensor 1 ist die Sonde, die der Container selbst benutzt: sie fasst nichts an,
was ausfallen kann. Sie sagt „der Prozess lebt" und nicht mehr — und genau
deshalb darf sie nicht die einzige sein. Ein Prozess lebt auch, wenn die
Datenbank weg ist.

Sensor 2 und 3 sind die tiefen. Sie antworten **immer mit HTTP 200**; der
Zustand steht im Rumpf. Das ist Absicht: ein Sensor, der schon am Statuscode
scheitert, liest die Begründung nicht mehr — und die Begründung ist der Zweck.

## 3 · Sensor 2 einrichten (je Kundenseite)

**Token setzen.** Auf dem Anwendungsserver, in der `.env` neben der
Compose-Datei:

```bash
MAGISTER_HEALTH_TOKEN=$(openssl rand -hex 32)
```

Ohne Token gibt es die Route nicht — sie antwortet mit 404 wie ein Tippfehler
im Pfad. Ein falscher Token bekommt dieselbe Antwort; wer rät, soll nicht
erfahren, dass er nah dran war.

**In PRTG:** Sensor „HTTP XML/REST Value", URL
`https://<kunde>.mgmt.vitabrevis.ch/healthz/stack`, und den Token als Kopfzeile
`X-Magister-Health` mitgeben (in PRTG über eine `.header`-Datei im
`Custom Sensors\rest`-Verzeichnis oder die REST-Custom-Variante).

Kann der gewählte Sensortyp keine Kopfzeilen, geht auch
`…/healthz/stack?token=<wert>`. Dann steht der Token in den
Zugriffsprotokollen des Reverse-Proxy — akzeptabel in einem internen Netz,
aber die Kopfzeile ist der richtige Weg.

**Kanal:** `$.status` als Wert, Grenzwerte „Warnung ab 1", „Fehler ab 2".

Die Antwort sieht so aus:

```json
{
  "status": 2,
  "state": "critical",
  "tenant": "thun",
  "version": "0.7.0",
  "checks": [
    {"name": "registry", "status": 0, "detail": "Mandant thun"},
    {"name": "tenant_status", "status": 0, "detail": "aktiv"},
    {"name": "schema_version", "status": 2, "detail": "Schema steht auf 0045_…, der Code auf 0046_… — die Seite antwortet mit Wartung, bis die Migration gelaufen ist"},
    {"name": "tenant_key", "status": 0, "detail": "vorhanden"},
    {"name": "database", "status": 0, "detail": "erreichbar als r_thun"},
    {"name": "ad_sync", "status": 1, "detail": "letzter vollständiger Abgleich vor 95 Minuten (Intervall 15 Minuten)"}
  ]
}
```

## 4 · Was die einzelnen Befunde heissen

| Prüfung | `2` heisst | Was zu tun ist |
|---|---|---|
| `registry` | Der Hostname zeigt hierher, aber kein Kunde beansprucht ihn. | DNS oder Kundeneintrag in der Konsole korrigieren. Der häufigste Betriebsfehler. |
| `tenant_status` | Kunde in Bereitstellung oder Offboarding — er wird nicht bedient. | Bereitstellung in der Konsole weiterführen („Weiter ab …"). Bei `1` (gesperrt) ist es eine Entscheidung, keine Störung. |
| `schema_version` | Das Schema hängt hinter dem Code. Die Seite antwortet mit Wartung. | `magister-cli tenants migrate` für diesen Kunden. Genau der Fall, den die Versions-Schranke absichtlich erzwingt. |
| `tenant_key` | Der Kundenschlüssel fehlt in der Umgebung. | `MAGISTER_TENANT_AUDIT_KEY_<REF>` und Verwandte setzen, Dienst neu starten. |
| `database` | Die Verbindung **als Mandantenrolle** scheitert. | Rollenpasswort, DSN-Verweis, Postgres. Die Prüfung deckt DSN, Anmeldung, Schema und Scope in einem Schritt ab. |
| `ad_sync` | Seit über 24 Stunden kein vollständiger Abgleich. | Agent, Dienstkonto, Domänencontroller — Sensor 4 sagt meist, welcher. Neue Konten kommen bis dahin nicht an. |

## 5 · Sensor 3 und der Zugang zur Konsole

Die Konsole liegt hinter drei Schichten: interne Adresse, Client-Zertifikat,
Marker (siehe [console-listener.md](console-listener.md)). PRTG braucht deshalb
ein **eigenes Client-Zertifikat** aus der Plattform-CA — ein „Monitor"-Zertifikat,
kein Operator-Zertifikat. Es öffnet genau diese eine Route: alles andere
verlangt zusätzlich eine Operator-Sitzung mit zweitem Faktor.

Ausstellen wie ein Operator-Zertifikat ([platform-ca.md](platform-ca.md) §4),
Common Name z.B. `prtg-monitor`. **Nicht** in `console_operators` eintragen —
der Monitor ist keine Person (ADR-0020 D4).

## 6 · Sensor 4 (Flotte)

```bash
python -m cockpit_api.cli.fleet_check
```

Exit-Code 0/1/2, Ausgabe je Befund eine Zeile. In PRTG als „SSH Script"-Sensor
auf dem Konsolen-Host. Was er findet: abgelaufene und nicht erneuerte
Agentenzertifikate, stille Agenten, zurückhängende Agent-Versionen, aktive
Kunden ganz ohne Agent. Einzelheiten im Runbook
[betrieb-im-grossen.md](betrieb-im-grossen.md).

## 7 · Was bewusst **nicht** überwacht wird

* **Keine LDAP-Probe im Minutentakt.** Eine Sonde, die das Verzeichnis
  anfasst, ist bei zwanzig Kunden eine Last auf zwanzig fremden
  Domänencontrollern — und über den Connector wäre sie ein Auftrag je
  Abfrage. Stattdessen das Alter des letzten Abgleichs: steht in der
  Datenbank, kostet nichts, sagt dasselbe einen Takt später.
* **Keine Personendaten.** Keine der Sonden nennt einen Namen, eine Klasse
  oder eine Zahl von Schülern. Was sie nennen, ist Betriebszustand.
* **Keine Alarmierung aus Magister heraus.** Siehe §1.

## 8 · Prüfen, dass es wirklich geht

```bash
# Kundenseite, tief
curl -sS -H "X-Magister-Health: $MAGISTER_HEALTH_TOKEN" \
  https://thun.mgmt.vitabrevis.ch/healthz/stack | jq .status

# Konsole, tief (mit dem Monitor-Zertifikat)
curl -sS --cert prtg-monitor.pem --key prtg-monitor-key.pem \
  https://console.mgmt.vitabrevis.ch:4444/api/health/stack | jq .status

# Flotte
python -m cockpit_api.cli.fleet_check; echo "Exit: $?"
```

**Der Test, der zählt**, ist der negative: einen Kunden in der Konsole sperren
und nachsehen, ob Sensor 2 gelb wird. Eine Überwachung, die nie etwas gemeldet
hat, ist nicht ruhig — sie ist unbewiesen.
