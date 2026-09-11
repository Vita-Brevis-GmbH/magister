# Runbook · Konsolen-Listener (TCP 4444)

> Die Global-Management-Konsole darf aus dem Internet **nicht** erreichbar sein
> ([ADR-0015](../adr/0015-authentisierungs-haertung.md) D1). Der Kunden-Zugang
> auf 443 bleibt öffentlich und ist mit MFA geschützt; das Management liegt auf
> einem eigenen Port, gebunden an eine interne Adresse.
> Status: **Listener gebaut und verifiziert; die Konsolen-Oberfläche liegt
> seit ADR-0020 dahinter und wird von Caddy aus `cockpit/web/dist` ausgeliefert.**

## 1 · Drei Schichten

| Schicht | Massnahme | Wo | Was sie verhindert |
|---------|-----------|-----|--------------------|
| 1 | Port-Mapping auf die Management-Adresse (`10.0.0.5:4444`), nicht `0.0.0.0` | `cockpit/deploy/docker-compose.yml` | Der Port existiert im Internet gar nicht. Das ist die eigentliche Trennlinie. |
| 2 | `client_auth require_and_verify` gegen die Plattform-CA | `cockpit/deploy/caddy/Caddyfile` | Wer den Port erreicht, aber kein Operator-Zertifikat hat, kommt über den TLS-Handshake nicht hinaus — es gibt keine HTTP-Antwort. |
| 3 | Marker-Riegel: die API verwirft jede Anfrage ohne `X-Magister-Management` | `cockpit/api/cockpit_api/management_guard.py` | Eine zweite Route zur API (falsches Port-Mapping, Container-Netz, Fehlkonfiguration in Zukunft) läuft ins 404. |

Ehrlich zur Reichweite: **Schicht 3 kann Schicht 1 und 2 nicht überprüfen.**
Der Marker beweist nur, dass die Anfrage durch *einen* Reverse-Proxy kam, der
ihn setzt — nicht, dass dieser Proxy intern gebunden war oder ein Client-Zertifikat
geprüft hat. Kommt der Marker jemandem in die Hände und ist der Port trotzdem
offen, ist der Riegel wirkungslos. Die Sicherheit steht und fällt mit Schicht 1;
Schichten 2 und 3 sind Tiefe, keine Ersatzmassnahmen.

Was die API beim Start *doch* prüfen kann: dass `COCKPIT_PUBLISHED_ADDRESS`
keine Wildcard-Adresse ist (`0.0.0.0`, `::`, `*`, leer) und dass bei
`COCKPIT_REQUIRE_MANAGEMENT_LISTENER=1` überhaupt ein Marker gesetzt ist.
Beides bricht den Start ab, statt still eine offene Konsole zu starten.

## 2 · Einrichten

### 2.1 Zertifikate

Drei Dateien müssen in `cockpit/deploy/certs/` liegen, bevor der Stack startet
(der Caddy-Container verweigert sonst den Start und sagt, welche fehlt):

| Datei | Inhalt | Herkunft |
|-------|--------|----------|
| `platform-ca.pem` | Root + Intermediate "Operator" | [Runbook Plattform-CA](platform-ca.md) §4 |
| `console.pem` | Serverzertifikat für `console.magister.ch` (Kette) | interne CA oder öffentliches Zertifikat |
| `console-key.pem` | privater Schlüssel dazu, `0600` | ebd. |

### 2.1a · Namen und ein Wildcard, das nicht so weit reicht, wie es aussieht

Festgelegt (2026-09-11): Kundenseiten und Konsole liegen unter
`<kunde>.mgmt.vitabrevis.ch` beziehungsweise `console.mgmt.vitabrevis.ch`, der
Connector-Endpunkt öffentlich unter `connect.vitabrevis.ch`.

**Ein Wildcard-Zertifikat gilt für genau eine Ebene.** `*.vitabrevis.ch` deckt
`connect.vitabrevis.ch` ab — aber **nicht** `thun.mgmt.vitabrevis.ch` und auch
nicht `console.mgmt.vitabrevis.ch`. Dafür braucht es `*.mgmt.vitabrevis.ch`,
als zweites Wildcard oder als SAN im selben Zertifikat.

Das ist kein Detail, das sich später nachziehen lässt: fehlt es, scheitert
jede Kundenseite am TLS-Handshake, und zwar für alle gleichzeitig. Beim
Bestellen mitbestellen.

`platform-ca.pem` ist der **Trust Pool für Client-Zertifikate** — nur wer ein
von dieser Kette signiertes Zertifikat vorweist, kommt durch den Handshake.
Deshalb dort ausschliesslich die Operator-Kette hinterlegen, nie ein
öffentliches CA-Bundle: sonst gilt jedes Zertifikat der Welt.

### 2.2 `.env` neben der Compose-Datei

```bash
COCKPIT_BIND_ADDRESS=10.0.0.5          # die Management-Adresse. NICHT 0.0.0.0.
COCKPIT_HOSTNAME=console.mgmt.vitabrevis.ch  # Name auf console.pem
COCKPIT_MANAGEMENT_MARKER=$(openssl rand -hex 32)
COCKPIT_BOOTSTRAP_TOKEN=$(openssl rand -hex 32)
```

Der Marker ist ein gemeinsames Geheimnis zwischen Caddy und API und wird von
Caddy auf **jede** weitergeleitete Anfrage gesetzt (`header_up`) — ein vom
Client mitgeschickter Wert wird dabei überschrieben, nicht ergänzt. Er gehört
in den Passwort-Safe wie ein Datenbank-Passwort und wird bei Rotation auf beiden
Seiten gleichzeitig getauscht (kurzer Neustart, kein Zero-Downtime-Verfahren).

### 2.3 Operator-Zertifikate ausrollen

Ein Zertifikat **pro Gerät**, nicht pro Person: ein verlorener Laptop soll
widerrufbar sein, ohne dass die Person ihren Zugang von den anderen Geräten
verliert. Ausstellung nach [Runbook Plattform-CA](platform-ca.md) §5, Auslieferung
als PKCS#12 in den Zertifikatsspeicher des Geräts. Das Passwort der `.p12` läuft
über einen anderen Kanal als die Datei selbst.

## 3 · Verifizieren

Nach jeder Änderung an Compose-Datei, Caddyfile oder Zertifikaten alle drei
Kommandos ausführen. Das erste ist das wichtigste — es prüft die Schicht, die
wirklich trägt.

```bash
# 1 · Handshake MUSS ohne Client-Zertifikat scheitern.
#     Erwartet: curl-Exit 56, "tlsv13 alert certificate required", KEINE HTTP-Antwort.
curl -sv --cacert certs/platform-ca.pem https://console.magister.ch:4444/api/health
echo "Exit: $?"   # 56 = gut. 0 = SOFORT eskalieren, der Handshake ist offen.

# 2 · Mit Zertifikat MUSS es durchgehen.
#     Erwartet: {"status":"ok"}
curl -s --cacert certs/platform-ca.pem \
     --cert operator.pem --key operator-key.pem \
     https://console.magister.ch:4444/api/health

# 3 · Die Bindung MUSS die Management-Adresse zeigen, nicht die Wildcard.
#     Erwartet: 10.0.0.5:4444 — steht dort 0.0.0.0:4444 oder *:4444, ist die
#     Konsole aus dem Internet erreichbar, sobald die Firewall den Port öffnet.
ss -tlnp | grep 4444
```

Zusätzlich einmal von aussen prüfen (vom Internet, nicht aus dem
Management-Netz): `nc -zv <öffentliche-IP> 4444` muss in einen Timeout laufen.
Fortigate und WAF filtern den Port ohnehin — aber diese Prüfung deckt den Fall
auf, dass er dort versehentlich freigegeben wurde.

## 4 · Wenn es nicht geht

| Symptom | Ursache | Behebung |
|---------|---------|----------|
| Caddy startet nicht, meldet fehlende Datei | eine der drei Zertifikatsdateien fehlt | §2.1; der Container prüft absichtlich vorab, statt ohne Client-Prüfung zu starten |
| API startet nicht: "Wildcard-Adresse" | `COCKPIT_BIND_ADDRESS` ist `0.0.0.0` oder leer | die Management-Adresse eintragen; nicht den Start-Check abschalten |
| API startet nicht: Marker fehlt | `COCKPIT_MANAGEMENT_MARKER` nicht gesetzt | `openssl rand -hex 32`, auf beiden Seiten gleich |
| Alle API-Pfade geben 404, `/api/health` geht | Marker in Caddy und API verschieden | beide `.env`-Werte vergleichen; `/api/health` ist absichtlich vom Riegel ausgenommen, damit der Compose-Healthcheck funktioniert |
| `curl: (35)`/`(58)` mit Zertifikat | Zertifikat nicht von `platform-ca.pem` signiert oder abgelaufen | Kette prüfen: `openssl verify -CAfile platform-ca.pem operator.pem` |
| Browser fragt nicht nach dem Zertifikat | `.p12` nicht im Zertifikatsspeicher, oder falscher Host im SNI | Import prüfen; Caddy erzwingt bei aktivem Client-Auth strikte SNI-Host-Prüfung, der Name muss exakt `COCKPIT_HOSTNAME` sein |

## 5 · Die Oberfläche und der zweite Faktor

Seit ADR-0020 liefert dieser Listener **auch die Konsolen-Oberfläche** aus:
Nicht-API-Pfade gehen nach `/srv/console` (`try_files {path} /index.html`).
Dieselbe Herkunft wie die API, damit der Sitzungs-Cookie erststellig bleibt.
Das Verzeichnis kommt als Mount aus `cockpit/web/dist` — die Oberfläche ändert
sich öfter als der Listener, und ein Neubau des Caddy-Images dafür wäre Aufwand
ohne Grund. Vor dem ersten Start also `cd cockpit/web && pnpm build`; ohne
`dist` antwortet der Listener mit 404 auf alles ausser `/api/*`.

Der API-Block gibt zusätzlich das geprüfte Client-Zertifikat weiter:
`header_up X-Console-Client-Cert {http.request.tls.client.certificate_der_base64}`.
Damit erkennt die Anwendung die **Person** (SPKI-Fingerprint → Zeile in
`console_operators`, ADR-0020 D1) und nicht nur, dass irgendein gültiges
Zertifikat vorlag. `certificate_pem` wäre an dieser Stelle falsch: ein PEM
enthält Zeilenumbrüche, Gos `net/http` weist einen solchen Header-Wert ab, und
Caddy antwortet mit 502.

Der zweite Faktor der Person ist **TOTP**, lokal und ohne fremden Dienst
(ADR-0020 D2) — nicht Conditional Access in Entra ID, wie ADR-0013 D2 vorsah.
Das Client-Zertifikat bindet weiterhin das Gerät und ersetzt keinen zweiten
Faktor. Operator anlegen, widerrufen, Faktor verloren:
[konsolen-operator.md](konsolen-operator.md).

## 6 · Was noch fehlt

- **Verschiebung an den Plattform-Rand:** langfristig gehört die Sperre auf
  Fortigate/WAF-Ebene, nicht in die Applikation. Der Listener bleibt trotzdem —
  eine Applikation, die sich selbst nicht öffentlich stellen kann, ist einen
  Fehlklick in der Firewall wert.
- **WebAuthn** statt TOTP: derselbe Platz im Code, ein anderer Faktor. Fällig,
  sobald das Betreiber-Team über eine Handvoll Personen hinauswächst — TOTP ist
  nicht phishing-resistent (ADR-0020 D2).

## Querverweise

- [ADR-0015](../adr/0015-authentisierungs-haertung.md) — Entscheid D1
- [ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md) — Entscheid D3 (Listener-Aufteilung 443 / 4444 / 46200)
- [ADR-0020](../adr/0020-konsolen-anmeldung.md) — Zertifikat als Identität, TOTP als zweiter Faktor
- [Runbook Plattform-CA](platform-ca.md) — Ausstellung der Operator-Zertifikate
- [Runbook Konsolen-Operator](konsolen-operator.md) — Zeile anlegen, erstes Anmelden, Widerruf
- `cockpit/deploy/caddy/README.md` — Dateien und Marker aus Betriebssicht
