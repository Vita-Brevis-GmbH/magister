# ADR-0020 · Die Konsole erkennt Personen am Zertifikat und bestätigt sie mit TOTP

**Status:** angenommen, 2026-09-11
**Kontext:** [ADR-0015 D1](0015-authentisierungs-haertung.md) (Konsolen-Port,
Client-Zertifikate), [ADR-0015 D2](0015-authentisierungs-haertung.md) (TOTP für
das lokale Notkonto), [ADR-0013 D2](0013-mandantenfaehigkeit-control-plane.md)
(dort war Entra ID vorgesehen), [ADR-0019](0019-operator-zugriff.md)
(Operator-Zugriff), Entscheid E21

## Problem

Die Konsole hat heute **einen** Nachweis: einen Bearer-Token. Drei Schwächen,
und die zweite ist die, um die es geht:

1. Ein Token lässt sich kopieren, ohne dass es jemand merkt, und der
   Bootstrap-Token läuft nicht ab.
2. **Es steht keine Person hinter einer Handlung.** `actor` ist ein
   Freitextfeld, das der Aufrufer mitschickt. Wer den Token hat, tippt jeden
   Namen — auch den des Kollegen. Das Protokoll der Konsole sagt, was der
   Aufrufer *behauptet*.
3. Widerrufen heisst den Token für alle wechseln.

Punkt 2 wirkt bis in die Kundenprotokolle: `POST /operator-access` nimmt den
Namen des Operators aus dem Anfragekörper (ADR-0019). Dieser Name reist
signiert mit und landet unverändert im Audit des Kunden — er ist dort die
Auskunft „wer hat zugesehen". Solange ihn der Aufrufer frei setzt, ist die
Auskunft eine Behauptung.

Was **nicht** das Problem ist: die Erreichbarkeit. Der Port liegt auf einer
internen Adresse, und der Listener verlangt schon heute ein Client-Zertifikat
der Plattform-CA (ADR-0015 D1, Schichten 1 und 2). Die Tür ist zu. Es fehlt
die Auskunft, **wer** durchgegangen ist.

ADR-0013 D2 sah dafür Entra ID mit Conditional Access vor (Entscheid E21).
Dieser ADR entscheidet anders.

## Entscheidung

### D1 · Die Identität ist der öffentliche Schlüssel des Zertifikats, nicht sein Name

Caddy prüft das Client-Zertifikat gegen die Plattform-CA und gibt es als
DER-base64 weiter. Die Konsole bildet daraus den **SPKI-Fingerprint** (SHA-256
über den DER-kodierten öffentlichen Schlüssel) und sucht damit die Zeile in
`console_operators`.

Nicht über den `CN`: ein Name im Zertifikat ist eine Zeichenkette, die bei der
Ausstellung entsteht, und „Identität per Namensdisziplin" hält genau so lange,
bis zwei Zertifikate denselben Namen tragen oder eines neu ausgestellt wird.
Der Fingerprint gehört zum Schlüsselpaar: er ist eindeutig, und ein neues
Zertifikat für dieselbe Person ist eine bewusste Änderung an einer Zeile.

Dasselbe Verfahren wie bei den Connector-Agenten (ADR-0014) — inklusive des
Helfers, der dort schon steht. Und inklusive der Lehre, die dort schon
bezahlt wurde: der Platzhalter ist
`{http.request.tls.client.certificate_der_base64}` und **nicht** `…_pem`. Ein
PEM enthält Zeilenumbrüche, Gos `net/http` weist einen solchen Header-Wert ab,
und Caddy antwortet mit 502.

**Was der Fingerprint nicht leistet:** er bindet ein **Gerät**, keine Person.
Ein `.p12` im Zertifikatsspeicher ist eine Datei und kopierbar. Deshalb D2.

### D2 · TOTP ist der zweite Faktor, und er ist lokal

Nach dem Zertifikat verlangt die Konsole einen sechsstelligen Code (RFC 6238).
Erst danach entsteht eine Sitzung.

Kein Entra, kein Conditional Access, keine dritte Partei. Der Grund ist
derselbe, mit dem der Operator-Zugriff offline geprüft wird (ADR-0019 D3):
**in die Konsole geht man, wenn etwas kaputt ist.** Eine Anmeldung, die einen
fremden Dienst braucht, ist genau dann nicht verfügbar, wenn sie gebraucht
wird. Bei zwei Schlüsselhaltern wiegt der Vorteil eines zentralen
Lebenszyklus das nicht auf.

**Ehrlich zur Reichweite:** TOTP ist **nicht** phishing-resistent. Ein Code
kann abgefragt und weitergegeben werden. Was das hier relativiert, ist nicht
Zuversicht, sondern die Reihenfolge der Schichten: um einen Code zu
missbrauchen, braucht jemand zusätzlich **Netzzugang auf die interne Adresse**
und **ein gültiges Client-Zertifikat**. Wer beides hat, ist schon drin. Wächst
das Betreiber-Team oder wird die Konsole von aussen erreichbar, ist WebAuthn
der nächste Schritt — dieselbe Stelle im Code, ein anderer Faktor.

Die Mechanik ist die von ADR-0015 D2, bewusst dieselbe: Geheimnis
verschlüsselt (pgcrypto, `COCKPIT_SECRET_KEY`), letzter akzeptierter Zeitschritt
gespeichert (ein Code ist **einmal** gültig, auch innerhalb seines Fensters),
zehn Wiederherstellungscodes als argon2id-Hashes, Sperre nach fünf
Fehlversuchen. Nicht neu erfunden, sondern von einer Stelle, die im Betrieb
steht.

### D3 · `actor` wird abgeleitet, nicht mitgeschickt

Die drei Schemata mit `actor: str` verlieren das Feld. Der Name kommt aus der
Sitzung.

Das ist die eigentliche Wirkung dieses ADR. Ein Protokoll, in dem der
Handelnde einträgt, wer er war, ist eine Notiz; eines, in dem es die
Anwendung einträgt, ist ein Nachweis. Für `POST /operator-access` heisst das:
der Name, der beim Kunden im Audit steht, ist der Name der angemeldeten
Person — nicht mehr eine Zeichenkette aus dem Anfragekörper.

### D4 · Drei Arten von Aufrufern, und nur eine ist eine Person

| Art | Woran erkannt | Darf |
|---|---|---|
| **Person** | Sitzungs-Cookie (Zertifikat + TOTP) | alles |
| **Dienst** | Service-Token (ADR: hardening M-01) | nur was kein `actor` braucht — der Runner holt Update-Aufträge ab |
| **Notzugang** | Bootstrap-Token | alles, und zwar unter dem Namen `bootstrap-token`, damit es im Protokoll auffällt |

Ein Dienst-Token kann die Rechte-Matrix eines Kunden **nicht** mehr ändern und
keinen Operator-Zugriff ausstellen: dort verlangt die Prüfung eine Person. Der
Runner braucht das nicht, und ein Token, das im Container liegt, soll nicht
können, was einen Namen ins Kundenprotokoll schreibt.

Der Bootstrap-Token bleibt — er ist der einzige Weg in eine frisch
ausgerollte Konsole, in der noch kein Operator eingetragen ist. Er verliert
nur seine Rolle als Alltagszugang.

### D5 · Einen Operator anlegen ist ein Handgriff mit drei Teilen

Zertifikat ausstellen (Plattform-CA, Runbook existiert) → Fingerprint bilden →
Zeile anlegen. Der dritte Teil ist ein CLI-Befehl der Konsole und **keine**
Oberfläche: bei zwei Personen wäre eine Benutzerverwaltung mehr Fläche als
Nutzen, und sie wäre die Fläche, über die man sich selbst Rechte gibt.

Das Enrolment des zweiten Faktors macht die Person selbst, beim ersten
Anmelden: Geheimnis und Wiederherstellungscodes erscheinen **einmal**. Wer
neu anfängt, bekommt damit kein halb fertiges Konto — ohne bestätigten Code
gibt es keine Sitzung.

## Folgen

**Gut:**

- Im Protokoll steht, wer etwas getan hat, und im Kundenprotokoll steht, wer
  zugesehen hat — beides von der Anwendung eingetragen.
- Widerruf pro Person: Zeile abschalten, Zertifikat nicht erneuern.
- Zwei Faktoren, und keiner davon hängt an einem fremden Dienst.
- E21 wird gegenstandslos.

**Preis:**

- **TOTP ist nicht phishing-resistent.** Siehe D2; die Schichten davor tragen
  das, und der Weg zu WebAuthn bleibt offen.
- Kein zentraler Lebenszyklus. Verlässt jemand die Firma, sind es zwei
  Handgriffe (Zeile abschalten, Zertifikat sperren) statt eines in Entra. Bei
  zwei Personen ist das vertretbar, bei zehn nicht mehr.
- Ein Geheimnis mehr auf dem Konsolen-Server (`COCKPIT_SECRET_KEY`). Ohne ihn
  ist kein TOTP prüfbar — er gehört in die Sicherung und in die
  Schlüsselrotation.
- Die Wiederherstellungscodes sind der letzte Ausweg. Sind sie weg **und** das
  Telefon weg, hilft nur der Bootstrap-Token.

## Verworfen

**Entra ID mit Conditional Access (E21, ADR-0013 D2).** Der stärkere Faktor
und der bequemere Lebenszyklus — und eine Anmeldung, die einen fremden Dienst
braucht, um an das Werkzeug zu kommen, mit dem man Störungen behebt. Verworfen
an diesem Punkt. Bleibt die richtige Antwort, sobald das Betreiber-Team über
eine Handvoll Personen hinauswächst.

**Nur das Client-Zertifikat, ohne zweiten Faktor.** Billiger, und das
Zertifikat bindet ein Gerät statt einer Person (D1). Eine kopierte
`.p12`-Datei wäre dann der ganze Zugang.

**Identität über den `CN` des Zertifikats.** Siehe D1.

**Eine Benutzerverwaltung in der Oberfläche.** Siehe D5.
