# ADR 0014: AD-Connector-Agent — ausgehend, mTLS mit privater CA plus API-Key

**Status:** Vorschlag · 2026-09-08
**Kontext:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) D10 — eine
gehostete Magister-Plattform muss das Active Directory im Kundennetz erreichen.
**Baut auf:** [ADR-0011](0011-ad-service-boundary-10-container-split.md) (strikte AD-Grenze)

## Problem

Heute läuft Magister im Kundennetz und spricht LDAPS direkt mit den
Domänencontrollern. Gehostet ist das nicht möglich, und die naheliegenden
Auswege sind alle schlecht:

- LDAPS von der Plattform zum Kunden über das Internet öffnet einen
  Domänencontroller gegen aussen. Kommt nicht in Frage.
- Ein eingehender Port beim Kunden (auch nur für den Agenten) verlangt pro
  Kunde eine Firewall-Freigabe und NAT.
- Ein Site-to-Site-Tunnel stellt die Plattform *in* das Kundennetz und macht
  Least Privilege und operationsgenaues Auditing praktisch unmöglich.

Gleichzeitig ist der Passwort-Reset im on-prem AD die Kernfunktion des
Produkts — sie darf nicht wegfallen.

## Entscheidung

Ein **Connector-Agent** beim Kunden, der ausschliesslich **ausgehend**
telefoniert. Kein eingehender Port, kein Tunnel, kein DNS-Eintrag beim Kunden.
LDAPS bleibt vollständig im Kundennetz.

### 1 · Netzweg

Der Agent baut die Verbindung auf, in genau eine Richtung:

```
Kundennetz                                    Vita-Brevis-Plattform
┌───────────────────────────┐                 ┌──────────────────────────┐
│ Agent ──LDAPS 636──▶ DCs  │                 │ magister-api             │
│   │                       │                 │   │ Auftragswarteschlange│
│   └── TCP 46200 ausgehend ┼────────────────▶│ connect.magister.ch:46200│
└───────────────────────────┘                 └──────────────────────────┘
```

Die einzige Firewall-Anforderung beim Kunden: **ausgehend TCP 46200 zu einem
Hostnamen**. Nichts eingehend.

**Eigener Port, getrennt von der Kundenoberfläche.** Der Connector hört auf
`0.0.0.0:46200`, nicht auf 443. Damit hat er eine eigene TLS- und
Client-Auth-Politik, eine eigene WAF- und Fortigate-Regel und eine eigene
Log-Spur; ein Fehler in der Kundenoberfläche kann den Connector-Kanal nicht
treffen und umgekehrt. Auf 46200 wird **ausschliesslich** mit Client-Zertifikat
gesprochen — ein Browser oder Scanner bekommt dort keinen Handshake zustande.

Die Portbelegung der Plattform damit vollständig:

| Listener | Adresse | Wer | Client-Zertifikat |
|---|---|---|---|
| Kundenoberfläche | `0.0.0.0:443` | Lehr- und Leitungspersonen | nein, MFA über Entra |
| Konsole | `10.0.0.5:4444` | Global Admin, Operator | ja (ADR-0015 D1) |
| Connector | `0.0.0.0:46200` | Connector-Agenten | ja, erforderlich |

**Nur 46200, keine Rückfallebene auf 443** (Entscheid E11). Das ist eine
bewusste Entscheidung mit einem Preis: viele Firmen- und Gemeindenetze erlauben
ausgehend nur 80 und 443, teils nur über einen HTTP-Proxy. Dort muss die
Kunden-IT die Freigabe machen, sonst kommt der Agent nicht heraus.

Konsequenz für den Ablauf: die Firewall-Regel gehört in die
Onboarding-Voraussetzungen und muss **vor** dem Termin bestätigt sein, nicht
während der Installation entdeckt werden. Das Agent-Paket nennt sie, und der
Agent prüft beim ersten Start die Erreichbarkeit und meldet klar, wenn der Port
zu ist — statt still in einen Wiederholungszyklus zu gehen.

### 2 · Transport: Auftragsabruf plus Ergebnis-Rückgabe

- **Interaktive Operationen** (Passwort-Reset, Attribut-Schreiben, Anlegen):
  der Agent hält ein Long-Poll offen (`GET /connector/jobs?wait=25`), die
  Plattform legt den Auftrag hinein, der Agent führt ihn lokal gegen LDAPS aus
  und liefert das Ergebnis (`POST /connector/jobs/{id}/result`). Weil der Agent
  bereits wartet, ist die Zustellung praktisch sofort.
- **Wiederkehrender Sync** (grosse Lesevorgänge): der Agent blättert das AD
  lokal durch und **schiebt** die Seiten hoch, statt sie einzeln abholen zu
  lassen.

Plattformseitig ist das ein dritter Rücken hinter der bestehenden
`AdClient`-Schnittstelle (nach *direkt* und *eingehendem RPC*). Kein Aufrufer
im Code merkt den Unterschied, und ein späterer Wechsel auf einen
WebSocket-Kanal ändert nur diesen Rücken.

### 3 · Der Agent ist ein dummer Ausführer

Die Auftragsarten sind **genau die Methoden-Allowlist** aus
`magister_api/ad/rpc.py` (`ALLOWED_METHODS`) — ohne `authenticate`, das
[ADR-0015](0015-authentisierungs-haertung.md) entfernt. Geschäftslogik, Audit
und Scope bleiben auf der Plattform; die AD-Grenze aus ADR-0011 gilt unverändert.

**Es gibt keine Auftragsart „beliebiges LDAP", „beliebiges PowerShell" oder
„beliebiges Skript".** Das ist die wichtigste Eigenschaft des Entwurfs: eine
kompromittierte Plattform kann im Kundennetz nichts tun, was die Anwendung
nicht ohnehin dürfte.

### 4 · Authentisierung: zwei unabhängige Faktoren

Beide sind an **dieselbe** Kunden-plus-Agent-Zeile gebunden; einer allein wird
abgewiesen.

**a) mTLS gegen eine private, nicht publizierte CA.** Die Plattform betreibt
eine eigene CA: Offline-Root plus **zwei** Intermediates, eines für Connector-
und eines für Operator-Zertifikate (Aufbau und Zeremonien in
[`docs/runbooks/platform-ca.md`](../runbooks/platform-ca.md)). Kein
Intermediate pro Kunde — die Bindung an den Kunden macht die Anwendung, nicht
die Zertifikatskette.

Der Connector-Endpunkt verlangt `client_auth mode require_and_verify`;
zusätzlich vergleicht die Anwendung den SPKI-Fingerprint des Leaf-Zertifikats
mit der Agent-Zeile — ein gültiges Zertifikat eines *anderen* Kunden wird damit
abgewiesen, obwohl es aus derselben Kette stammt. Diese Prüfung ist die scharfe;
die Kette sortiert nur Fremdes aus. Der Agent pinnt umgekehrt den SPKI des
Plattform-Servers. TLS 1.3 only.

Weil die CA nicht öffentlich ist und nirgends publiziert wird, kann sich niemand
ein passendes Zertifikat bei einer öffentlichen CA besorgen. Ohne Client-Zertifikat
kommt der TLS-Handshake nicht einmal zustande: der Endpunkt ist für Scanner und
Browser stumm.

**b) API-Key pro Agent.** 32 Byte Zufall, in einem Header, plattformseitig
argon2id-gehasht gespeichert — unabhängig vom Zertifikat rotierbar.

### 5 · Der private Schlüssel verlässt nie den Agenten

Das Download-Paket enthält **kein Geheimnis**, sondern:

1. den signierten Installer,
2. das CA-Bundle der Plattform (für das Pinning),
3. ein **Einmal-Token** zur Anmeldung (TTL 24 h, einmalig einlösbar, an den
   Kunden gebunden).

Beim ersten Start erzeugt der Agent das Schlüsselpaar **lokal** — wo das
Betriebssystem es erlaubt nicht exportierbar (Windows CNG/DPAPI; unter Linux
Datei mit `0600`, Eigentümer der Dienstkonto-Benutzer) —, schickt einen CSR mit
dem Einmal-Token und erhält Leaf-Zertifikat plus API-Key zurück.

Damit liegt zu keinem Zeitpunkt ein privater Schlüssel in einer
herunterladbaren Datei. Das ist strikt besser, als ein fertiges Zertifikat
mitzuliefern.

### 6 · Lebenszyklus

- Leaf-Zertifikat 90 Tage, automatische Erneuerung bei zwei Dritteln der
  Laufzeit über denselben Kanal (neuer CSR, authentisiert mit dem noch gültigen
  Zertifikat plus API-Key).
- Widerruf ist ein Datenbank-Flag, geprüft bei jeder Anfrage — keine CRL, kein
  OCSP, keine Wartezeit.
- **Agent-Updates laufen automatisch**, Sicherheits-Updates sofort (Entscheid
  E10). Bei einer Lücke im Agenten ist das der Unterschied zwischen Stunden und
  Monaten. Version und Fingerprint der ganzen Flotte sind in der Konsole
  sichtbar; ein Update, das nicht anläuft, wird alarmiert. Ein Update tauscht
  nur die Binärdatei — Schlüssel, Zertifikat und lokale Politik des Agenten
  bleiben unangetastet.

### 7 · Der Kunde behält die Kontrolle

Der Agent erzwingt seine **eigene** Politik, lokal konfiguriert. Damit kann die
Plattform auch dann nicht mehr, wenn sie kompromittiert ist:

- OU-Allowlist: Operationen nur innerhalb der freigegebenen Organisationseinheiten.
- Denylist geschützter Gruppen (Domain Admins und Verwandte) — nie schreibbar.
- Operations-Allowlist: der Kunde kann einzelne Auftragsarten abschalten.
- Ein lokales, nur anfügbares Protokoll, das der Kunde selbst lesen kann.
- **Not-Aus:** Agent stoppen beendet jeden Plattformzugriff auf das AD. Sofort,
  ohne Vita Brevis.

### 8 · Integrität und Wiedereinspielschutz

- HMAC über Auftrags-Id und Ergebnis mit dem Agent-Key: ein terminierender
  Proxy kann ein Ergebnis nicht unbemerkt verändern.
- Auftrags-Ids sind einmalig; ein Ergebnis zu einem unbekannten oder bereits
  abgeschlossenen Auftrag wird verworfen.
- Auftrags-TTL (interaktiv 60 s): ein hängender Agent lässt die Anfrage
  fehlschlagen, statt den Auftrag später verspätet auszuführen.

### 9 · Wenn der Agent fehlt

Holt kein Agent den Auftrag innerhalb der TTL ab, antwortet die API mit `503`
und dem bestehenden Banner-Pfad „AD nicht erreichbar" — dieselbe Erfahrung wie
heute bei erschöpftem DC-Pool. Der Connector-Status steht in der Konsole.

### 10 · Bezug in der Konsole

Beim Erfassen eines Kunden (und später jederzeit unter Kunde → AD-Connector)
lädt man das Paket herunter: Windows-MSI als Dienst, Linux-`.deb` mit systemd,
oder OCI-Image. Installer signiert, SHA-256 angezeigt. Jeder Download und jede
Anmeldung eines Agenten wird auditiert; nach der Anmeldung zeigt die Konsole den
Fingerprint, damit der Kunde ihn vor Ort vergleichen kann.

## Nachträge aus der Umsetzung

Zwei Dinge kamen beim Bauen anders heraus als im Entwurf. Beide sind gegen
einen laufenden Caddy gemessen, nicht überlegt.

**Das Client-Zertifikat reist als base64-DER, nicht als PEM.** Der naheliegende
Platzhalter `{http.request.tls.client.certificate_pem}` liefert ein PEM mit
Zeilenumbrüchen — und Gos `net/http` weist einen Header-Wert mit Zeilenumbruch
ab. Der Reverse Proxy hätte damit **jede** Agent-Anfrage mit 502 beantwortet,
zuverlässig und von der ersten Minute an. Richtig ist
`{http.request.tls.client.certificate_der_base64}`; die Anwendung dekodiert
base64 und liest das DER. Nachgeprüft: ohne Client-Zertifikat scheitert der
Handshake (`tlsv13 alert certificate required`, keine HTTP-Antwort), mit
Zertifikat erreicht ein 420 Zeichen langer einzeiliger Header den Upstream, und
ein vom Client mitgeschickter `X-Connector-Client-Cert` wird von Caddy
**überschrieben**.

**Der Connector-Listener braucht seinen eigenen Marker.** Die Konsole verwirft
seit [ADR-0015](0015-authentisierungs-haertung.md) D1 jede Anfrage ohne
Management-Marker. Der Connector-Kanal liegt in derselben Anwendung, ist aber
absichtlich öffentlich — er müsste also vom Riegel ausgenommen werden. „Ohne
Marker erreichbar" wäre der falsche Weg: dann läge nach einer falsch geführten
Site-Block-Änderung auch `/api/*` der Konsole offen. Stattdessen hat jeder
Listener seinen Marker, und die beiden sind **nicht** austauschbar:

| Marker | auf `/api/*` | auf `/connector/*` |
|---|---|---|
| Management (4444) | durch | 404 |
| Connector (46200) | 404 | durch |

Gleiche Werte für beide heben die Trennung auf, deshalb bricht die Anwendung
beim Start ab, wenn sie gleich sind.

### Weitere Nachträge (Agent gebaut, Ende-zu-Ende gemessen)

Vier Befunde, jeder einzelne hätte den Kanal unbenutzbar gemacht, und keiner
davon war in einem Modultest sichtbar.

**Der Connector-Listener steht auf `verify_if_given`, nicht auf
`require_and_verify`.** Ein neuer Agent hat noch kein Zertifikat — es zu
bekommen ist der Zweck von `/connector/enroll`. Mit `require_and_verify`
scheitert der Handshake, **bevor** der Pfad bekannt ist; der Agent bekam beim
allerersten Aufruf `tlsv13 alert certificate required`. Eine Anmeldung wäre
also nie möglich gewesen. `verify_if_given` heisst: ohne Zertifikat kommt die
Verbindung zustande, mit Zertifikat wird die Kette geprüft — und alles außer
`/connector/enroll` verweigert ohne geprüftes Zertifikat den Dienst, diese
Prüfung liegt in der Anwendung, wo der Pfad bekannt ist. Damit schützt
`/connector/enroll` allein das Einmal-Token: 32 Byte Entropie, 24 Stunden,
einmal einlösbar. Das ist unvermeidbar und der Grund, warum das Token kurz
lebt und die Konsole danach den Fingerprint zeigt.

**httpx schickt seit 0.28 mit `verify=<str>` und `cert=(…)` kein
Client-Zertifikat mehr** — lautlos, die Gegenseite antwortet mit 401 wie bei
einem Agenten ohne Zertifikat. Der Agent baut deshalb einen ausdrücklichen
`ssl.SSLContext` mit `load_verify_locations` und `load_cert_chain`. Unsichtbar
in den Modultests, weil die `MockTransport` benutzen: ein Test, der den
Transport ersetzt, kann über den Transport nichts aussagen.

**Aufträge liefern nicht nur Objekte.** `result` war als `dict` typisiert;
`find_user_dn` gibt einen String, `fetch_user_groups` eine Liste,
`probe_service_connection` ein Bool. Damit wurde **jedes** erfolgreiche
Ergebnis mit 422 abgewiesen. Jetzt `Any`, mit einem Test über die Formen, die
die Allowlist wirklich liefert.

**Der Agent benutzt keinen Proxy aus der Umgebung** (`trust_env=False`). Über
den Kanal geht ein Client-Zertifikat, und ob es ankommt, darf nicht davon
abhängen, was jemand in ein Profil geschrieben hat. Braucht das Kundennetz
einen Proxy, steht er in der Konfiguration — ein Proxy, der TLS aufbricht,
macht die Client-Authentisierung ohnehin unmöglich und muss diesen Host
umgehen.

Dazu ein Fund an der Konsole, der nichts mit dem Connector zu tun hat, aber
denselben Ursprung: die Testsuite baute ihr Schema mit
`Base.metadata.create_all`. Damit erzeugt sie den Postgres-Typ aus denselben
Modell-Annahmen, mit denen die Anwendung schreibt — ein Fehler in einer
Annahme baut sich das passende Schema selbst. So blieb unentdeckt, dass
`IsolationMode.schema_only = "schema"` als *Name* gespeichert wurde
(`schema_only`), während die Migration den *Wert* anlegte (`schema`): alle
Tests grün, und die erste Kunden-Anlage gegen die echte Datenbank endete im
500er. Die Konsolen-Tests laufen seither über dasselbe Alembic wie
Produktion, und alle Enum-Spalten speichern über `values_callable` den Wert.

## Konsequenzen

**Positiv**

- LDAP verlässt das Kundennetz nie; die Plattform bekommt keinen Netzzugang
  dorthin, nur eine Auftragsschnittstelle.
- Keine eingehende Firewall-Regel, kein VPN, kein Netz-Engineering pro Kunde.
- Zwei unabhängige Faktoren, kein Geheimnis im Download, Zertifikat nicht
  öffentlich beschaffbar, Widerruf sofort wirksam.
- Der Kunde behält einen echten Not-Aus und kann die Plattform-Rechte lokal
  weiter einschränken.
- Eigener Port heisst eigene Politik und eigene Log-Spur: Kundenverkehr,
  Konsolenverkehr und Agentenverkehr sind auf der Edge sauber getrennt.
- Methoden-Allowlist und AD-Grenze aus ADR-0011 bleiben unverändert — der
  Agent ist ein neuer Transport, kein neues Rechtemodell.

**Negativ**

- Ein neues, auszulieferndes Stück Software: bauen, signieren, paketieren,
  aktualisieren, für zwei Betriebssysteme.
- Vita Brevis muss eine CA betreiben (Offline-Root, Schlüsselverwahrung).
- Der Agent wird zur Voraussetzung für Passwort-Resets; sein Ausfall ist ein
  Betriebsereignis, das überwacht werden muss.
- Der Kunde muss ausgehendes 46200 erlauben. Anders als 443 ist das in
  restriktiven Netzen keine Selbstverständlichkeit und ist ohne Rückfallebene
  eine harte Onboarding-Voraussetzung.
- Automatische Updates heissen: Vita Brevis kann jederzeit Code im Kundennetz
  austauschen. Das ist Vertrauen, das der Agent verdienen muss — signierte
  Pakete, reproduzierbare Builds und ein Rückrollweg gehören dazu.
- Interaktive Operationen bekommen einen zusätzlichen Zustellschritt.

## Alternativen verworfen

- **LDAPS von der Plattform zum Kunden**, auch mit IP-Allowlist: exponiert
  Domänencontroller nach aussen und braucht eingehendes NAT.
- **Site-to-Site-VPN / WireGuard:** funktioniert, stellt aber die Plattform ins
  Kundennetz. Auditing pro Operation und Least Privilege werden deutlich
  schwächer, und jeder Kunde braucht Netzarbeit.
- **Heutiges AD-RPC unverändert beim Kunden** (eingehender Listener): verlangt
  pro Kunde eine eingehende Freigabe.
- **Direkter AD-Zugriff für Einzelinstallationen behalten** (Agent nur für
  gehostete Kunden): wäre ein zweiter Codepfad für dieselbe Aufgabe, schlechter
  getestet und über Jahre auseinanderlaufend. On-prem nutzt denselben Agenten
  gegen denselben Endpunkt im eigenen Netz (ADR-0013 D8).
- **Client-Schlüssel im Download-Paket mitliefern:** ein privater Schlüssel in
  einer Datei hinter einem Download-Link. Die CSR-Anmeldung ist strikt besser.
- **Nur Entra, kein on-prem AD:** verliert den Passwort-Reset im lokalen AD und
  damit den Kern des Produkts.
- **Agent mit eigener Geschäftslogik** (Reset lokal entscheiden): würde Logik
  und Audit duplizieren und die ADR-0011-Grenze aufweichen.


## Nachtrag: Zertifikatserneuerung (2026-09-09)

Das Agentenzertifikat gilt 90 Tage (`connector_ca.AGENT_CERT_DAYS`). Der ADR
sagt nicht, wie es erneuert wird, und der Weg ohne Erneuerung wäre: Widerruf in
der Konsole, neues Einmal-Token, Besuch beim Kunden — alle drei Monate, je
Agent. Das hält niemand durch. Die Folge wäre nicht ein sauberer Ablauf,
sondern stillgelegte Agenten und, beim ersten Ärger, ein Zertifikat mit fünf
Jahren Laufzeit.

**Erneuert wird über den beglaubigten Kanal** (`POST /connector/renew`):
bestehendes Client-Zertifikat plus API-Key. Wer den aktuellen Schlüssel
besitzt, darf einen neuen bekommen. Ein Einmal-Token zu verlangen hiesse, das
Problem nur zu verschieben.

Drei Festlegungen, die dazugehören:

**N1 · Ein neues Schlüsselpaar, nicht dasselbe.** Denselben Schlüssel
weiterzuverwenden wäre einfacher — der Fingerprint bliebe gleich, es bräuchte
kein Übergangsfenster — und falsch: ein Schlüssel, der über Jahre auf einem
Kundenserver liegt, wird nie gewechselt. Die Erneuerung ist die Gelegenheit.
Ein CSR mit dem bestehenden Schlüssel wird abgewiesen.

**N2 · Beide Fingerprints gelten sieben Tage.** Der Fall, um den herum das
gebaut ist: die Plattform schreibt den neuen Fingerprint in die Agent-Zeile,
und die Antwort geht auf dem Rückweg verloren — abgebrochene Verbindung,
Proxy-Zeitüberschreitung, Neustart des Agenten in genau diesem Moment. Der
Agent klopft dann weiter mit dem alten Schlüssel an, auf eine Zeile, die ihn
nicht mehr kennt. Er wäre **ausgesperrt, und zwar endgültig**: ein neues
Einmal-Token kann nur ein Mensch ausstellen, und beim Kunden sitzt niemand
daneben.

`connector_agents.previous_spki_sha256` und `spki_rotated_at` lösen das.
Meldet sich der Agent mit dem **neuen** Fingerprint, ist die Erneuerung
bestätigt und der alte wird sofort verworfen — je kürzer er gilt, desto
besser. Nach Ablauf des Fensters gilt nur noch der neue; ein Schlüssel, der
ewig zusätzlich gilt, ist ein zweiter Schlüssel und kein Übergang.

**N3 · API-Key und HMAC-Schlüssel werden dabei nicht gedreht.** Beide in
derselben Antwort mitzudrehen wäre bequem und würde die Aussperrung wieder
möglich machen, die N2 verhindert: geht die Antwort verloren, hätte der Agent
einen alten API-Key zu einem neuen Zertifikat, und dann helfen auch zwei
gültige Fingerprints nicht. Ein Ding zur Zeit.

**Was ein widerrufener Agent nicht kann:** sich erneuern. `authenticate_agent`
prüft den Widerruf bei **jeder** Anfrage, und das ist der Grund, warum der
Widerruf ein Datenbank-Flag ist und keine CRL. Eine CRL wäre morgen aktuell,
und dieser Endpunkt wäre bis dahin der Weg um den Widerruf herum.

**Auf der Agentenseite** wechselt die Erneuerung zwei Dateien (Zertifikat und
Schlüssel), und dazwischen kann der Prozess sterben. Dann liegt ein neuer
Schlüssel neben einem alten Zertifikat, der TLS-Handshake scheitert lokal, und
im Protokoll steht eine OpenSSL-Meldung, die niemand mit „Erneuerung"
verbindet. Der Agent legt deshalb das alte Paar als `.prev` daneben und
stellt es beim Start wieder her, wenn das aktive Paar nicht zusammenpasst —
das alte Zertifikat gilt zu diesem Zeitpunkt noch (erneuert wird 30 Tage
vorher), und die Plattform akzeptiert den alten Fingerprint im
Übergangsfenster. Der Agent läuft also weiter und versucht es erneut.

Erneuert wird **30 Tage** vor Ablauf und nach einem Fehlschlag stündlich. 30
von 90 ist reichlich, und das ist Absicht: bei sieben Tagen wären
Betriebsferien beim Kunden genug, um den Agenten stillzulegen.
