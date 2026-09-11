# Runbook · Einen Operator für die Konsole einrichten

> Wer die Konsole bedienen darf, braucht zwei Dinge: ein Client-Zertifikat der
> Plattform-CA und einen zweiten Faktor auf seinem Telefon
> ([ADR-0020](../adr/0020-konsolen-anmeldung.md)).
> Das Zertifikat kommt aus der Zeremonie in
> [platform-ca.md](platform-ca.md), die Zeile aus einem CLI-Befehl, der zweite
> Faktor von der Person selbst.
> Betrifft: **Konsolen-Host** (`console.magister.ch`, interne Adresse).

## 1 · Warum es drei Teile sind

Weil die drei Teile **verschiedenen Leuten** gehören, und zwar absichtlich:

| Teil | Wer macht es | Warum nicht jemand anderes |
|---|---|---|
| Zertifikat ausstellen | zwei Schlüsselverwahrer, offline | Der CA-Schlüssel liegt im Tresor. |
| Zeile in `console_operators` anlegen | ein Betreiber, per CLI auf dem Host | Ein Zertifikat allein öffnet nichts. |
| Zweiten Faktor einrichten | **die Person selbst**, beim ersten Anmelden | Ein Betreiber, der einen fremden zweiten Faktor einrichten kann, ist kein zweiter Faktor. |

Die Konsole hat dafür **keine** Oberfläche, und das ist ADR-0020 D5: eine
Benutzerverwaltung wäre bei zwei Personen mehr Fläche als Nutzen — und sie
wäre die Fläche, über die man sich selbst Rechte gibt.

## 2 · Zertifikat ausstellen

Aus dem Intermediate **„Operator“** (nicht aus dem Connector-Intermediate —
ein verlorener Operator-Laptop soll die Agent-Flotte nicht berühren, siehe
platform-ca.md Abschnitt 2). Laufzeit ein Jahr.

```bash
# Auf dem Rechner der Person — der private Schlüssel entsteht dort und
# verlässt ihn nicht.
openssl ecparam -name prime256v1 -genkey -noout -out operator-vorname.key
openssl req -new -sha256 -key operator-vorname.key -out operator-vorname.csr \
  -subj "/C=CH/O=Vita Brevis GmbH/CN=vorname.nachname@vitabrevis.ch"

# CSR zum Plattform-Server, dort mit dem Operator-Intermediate signieren:
openssl x509 -req -in operator-vorname.csr \
  -CA operator-int.crt -CAkey operator-int.key -CAcreateserial \
  -sha256 -days 365 -out operator-vorname.crt \
  -extfile <(printf 'extendedKeyUsage=critical,clientAuth\nkeyUsage=critical,digitalSignature\n')

# Zurück auf den Rechner der Person, dort mit dem privaten Schlüssel und der
# Kette in eine .p12 für den Zertifikatsspeicher des Browsers:
openssl pkcs12 -export -out operator-vorname.p12 \
  -inkey operator-vorname.key -in operator-vorname.crt \
  -certfile operator-int.crt
```

Der `CN` ist Kosmetik: die Konsole erkennt die Person am **SPKI-Fingerprint**
des öffentlichen Schlüssels und nicht am Namen (ADR-0020 D1). Ein sauberer
`CN` hilft trotzdem beim Suchen im Zertifikatsspeicher.

Die `.p12` gehört in den Zertifikatsspeicher des Geräts und in den
Passwortspeicher — nicht in ein Postfach und nicht in einen Chat.

## 3 · Zeile anlegen

Auf dem Konsolen-Host, im Verzeichnis der API. Es braucht **nur den
öffentlichen Teil** des Zertifikats (`.crt`/`.pem`), nie den Schlüssel:

```bash
cd /opt/magister/cockpit/api
uv run python -m cockpit_api.cli.add_operator \
    --upn vorname.nachname@vitabrevis.ch \
    --name "Vorname Nachname" \
    --cert /tmp/operator-vorname.crt
# → vorname.nachname@vitabrevis.ch eingetragen (4c660618d82477aa…).
#   Der zweite Faktor wird beim ersten Anmelden eingerichtet.
```

Der `--upn` ist, was später in jedem Protokolleintrag steht — auch in dem beim
Kunden, wenn diese Person einen Operator-Zugriff öffnet
([ADR-0019](../adr/0019-operator-zugriff.md)). Also die echte Adresse, keine
Abkürzung.

Was der Befehl abweist:

- **Ein Zertifikat, das schon einer anderen Person gehört.** Ein Schlüsselpaar,
  eine Person — zwei Zeilen darauf hiessen zwei Namen für dieselbe Anmeldung.
- **Ein unlesbares Zertifikat.** Dann steht die Ursache von OpenSSL da.

Was er **nicht** tut: den zweiten Faktor anfassen. Siehe Abschnitt 1.

## 4 · Erstes Anmelden (macht die Person selbst)

1. `https://console.magister.ch:4444` öffnen. Der Browser fragt nach dem
   Zertifikat — wenn nicht, ist die `.p12` nicht im Zertifikatsspeicher.
2. Die Seite zeigt **„Zertifikat erkannt: Vorname Nachname“**. Steht dort
   stattdessen „Kein gültiges Client-Zertifikat“, siehe Abschnitt 6.
3. „Zweiten Faktor einrichten“ → QR-Code mit der Authenticator-App scannen.
4. **Die zehn Wiederherstellungscodes in den Passwortspeicher.** Sie kommen
   genau einmal. Ohne sie und ohne Telefon hilft nur noch der Bootstrap-Token.
5. Bestätigen, Code eintippen, angemeldet.

Ohne bestätigten Code entsteht **keine** Sitzung: es gibt keinen halb
eingerichteten Zustand, den man bewachen müsste.

## 5 · Widerruf

Zwei Handgriffe, und beide gehören dazu:

```bash
# 1. Die Zeile abschalten — wirkt sofort, bei der nächsten Anfrage.
uv run python -m cockpit_api.cli.add_operator \
    --upn vorname.nachname@vitabrevis.ch --disable
```

Zum Abschalten braucht es weder Zertifikat noch Namen: wer widerrufen wird,
hat unter Umständen genau das gerade verloren.

2. **Das Zertifikat nicht erneuern** und in der CA-Dokumentation als
   widerrufen vermerken (platform-ca.md Abschnitt 5). Es gibt keine CRL — der
   Widerruf ist die Zeile in der Datenbank, die die Anwendung bei jeder
   Anfrage prüft. Caddy prüft die Kette, die Anwendung den Fingerprint.

Laufende Sitzungen enden mit ihrer Frist (`COCKPIT_CONSOLE_SESSION_MINUTES`,
Vorgabe 4 Stunden). Soll jemand sofort draussen sein, zusätzlich:

```sql
-- Auf dem Konsolen-Host, Konsolen-Datenbank.
DELETE FROM console_sessions
 WHERE operator_id = (SELECT id FROM console_operators
                       WHERE upn = 'vorname.nachname@vitabrevis.ch');
```

## 6 · Wenn etwas nicht geht

| Fall | Was zu tun ist |
|---|---|
| **Der Browser kommt gar nicht an** (`ERR_CONNECTION_RESET`, kein Zertifikatsdialog) | Der Listener verlangt ein Zertifikat der Plattform-CA und bricht den Handshake sonst ab — das ist die zweite Schicht von ADR-0015 D1. Die `.p12` ist nicht installiert, oder der Browser bietet sie für diesen Host nicht an. |
| **„Kein gültiges Client-Zertifikat“** | Das Zertifikat kam durch, gehört aber zu keiner aktiven Zeile. Die Seite unterscheidet bewusst nicht, welches von beidem es ist. Prüfen: `SELECT upn, enabled, left(spki_fingerprint,12) FROM console_operators;` und den Fingerprint des Zertifikats dagegenhalten. |
| **Neues Gerät, gleiche Person** | Neues Zertifikat ausstellen, dann denselben `add_operator`-Befehl mit `--cert` auf das neue: der Fingerprint wird ersetzt, **der zweite Faktor bleibt**. Wer das Telefon behält, richtet es nicht neu ein. |
| **Telefon verloren, Wiederherstellungscodes da** | Mit einem Code anmelden (dasselbe Feld). Er ist danach verbraucht. Dann in Ruhe ein neues Gerät einrichten: Zeile zurücksetzen (nächste Zeile), neu anmelden. |
| **Telefon und Codes verloren** | Zweiten Faktor zurücksetzen — das ist ein Eingriff in der Datenbank, kein Befehl: `UPDATE console_operators SET totp_secret_enc = NULL, totp_confirmed_at = NULL, totp_last_step = NULL, recovery_codes = '[]' WHERE upn = '…';` Danach erzwingt das nächste Anmelden ein neues Enrolment. Absichtlich unbequem: es ist der Handgriff, mit dem man einen fremden zweiten Faktor austauschen könnte. |
| **Fünf falsche Codes** | Gesperrt für 15 Minuten, die Sperre läuft von selbst ab. Kein Knopf dafür. |
| **Niemand kommt herein** (frische Konsole, kein Operator eingetragen) | Der Bootstrap-Token (`COCKPIT_BOOTSTRAP_TOKEN`). Er steht auf der Anmeldeseite unter „Notzugang“ und schreibt `bootstrap-token` ins Protokoll — keinen Namen. Für die tägliche Arbeit ist er der falsche Weg. |
| **502 auf jeder API-Anfrage nach einer Caddy-Änderung** | Im `reverse_proxy` steht `certificate_pem` statt `certificate_der_base64`. Ein PEM enthält Zeilenumbrüche, und Gos `net/http` weist einen solchen Header-Wert ab. Diese Lehre ist zweimal bezahlt (ADR-0014, ADR-0020 D1). |

## 7 · Was in der Sicherung liegen muss

`COCKPIT_SECRET_KEY`. Damit ist das TOTP-Geheimnis in der Datenbank
verschlüsselt (pgcrypto); ohne ihn ist nach einer Wiederherstellung **kein**
zweiter Faktor prüfbar, und der Weg herein ist der Bootstrap-Token plus ein
neues Enrolment für jede Person. Er gehört in
[key-rotation.md](key-rotation.md) und in den Passwortspeicher.

## 8 · Wiederkehrende Aufgaben

| Wann | Was |
|---|---|
| **Jährlich** | Operator-Zertifikate erneuern (ein Jahr Laufzeit). Neues Zertifikat, `add_operator --cert`, fertig — der zweite Faktor bleibt. |
| **Jährlich** | `SELECT upn, name, enabled FROM console_operators;` gegen die Liste der Personen halten, die es noch geben soll. |
| **Bei Austritt** | Abschnitt 5, am selben Tag. |
