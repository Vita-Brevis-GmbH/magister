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

**Ein Vorbehalt, der vor dem ersten Kunden geklärt sein muss:** viele
Firmen- und Gemeindenetze erlauben ausgehend nur 80 und 443, teils nur über
einen HTTP-Proxy. Ein hoher Port wie 46200 wird dort blockiert, und der Agent
kommt nicht heraus. Der Agent muss deshalb entweder eine dokumentierte
Freigabe verlangen (Regel auf der Kunden-Firewall) oder auf 443 ausweichen
können. Siehe Entscheid E11 im Umsetzungsplan; die Empfehlung ist 46200 als
Standard plus 443 als Rückfallebene mit demselben mTLS-Zwang, damit ein
restriktives Kundennetz kein Ausschlusskriterium ist.

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
eine eigene CA (Offline-Root, pro Kunde ein Intermediate). Der
Connector-Endpunkt verlangt `client_auth mode require_and_verify`; zusätzlich
vergleicht die Anwendung den SPKI-Fingerprint des Leaf-Zertifikats mit der
Agent-Zeile — ein gültiges Zertifikat eines *anderen* Kunden wird damit
ebenfalls abgewiesen. Der Agent pinnt umgekehrt den SPKI des Plattform-Servers.
TLS 1.3 only.

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
- Agent-Updates über die Konsole angestossen, Version und Fingerprint dort
  sichtbar.

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
  restriktiven Netzen keine Selbstverständlichkeit und braucht eine
  Firewall-Regel beim Kunden (dafür die Rückfallebene oben).
- Interaktive Operationen bekommen einen zusätzlichen Zustellschritt.

## Alternativen verworfen

- **LDAPS von der Plattform zum Kunden**, auch mit IP-Allowlist: exponiert
  Domänencontroller nach aussen und braucht eingehendes NAT.
- **Site-to-Site-VPN / WireGuard:** funktioniert, stellt aber die Plattform ins
  Kundennetz. Auditing pro Operation und Least Privilege werden deutlich
  schwächer, und jeder Kunde braucht Netzarbeit.
- **Heutiges AD-RPC unverändert beim Kunden** (eingehender Listener): verlangt
  pro Kunde eine eingehende Freigabe.
- **Client-Schlüssel im Download-Paket mitliefern:** ein privater Schlüssel in
  einer Datei hinter einem Download-Link. Die CSR-Anmeldung ist strikt besser.
- **Nur Entra, kein on-prem AD:** verliert den Passwort-Reset im lokalen AD und
  damit den Kern des Produkts.
- **Agent mit eigener Geschäftslogik** (Reset lokal entscheiden): würde Logik
  und Audit duplizieren und die ADR-0011-Grenze aufweichen.
