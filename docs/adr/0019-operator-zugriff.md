# ADR-0019 · Ein Operator-Zugriff ist lesend, befristet und sichtbar

**Status:** angenommen, 2026-09-11
**Kontext:** [ADR-0013 D6](0013-mandantenfaehigkeit-control-plane.md) (Operator-Zugriff
befristet, begründet, sichtbar), [ADR-0015](0015-authentisierungs-haertung.md)
(Authentisierungs-Härtung), [ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md)
(Plattform-Capabilities), Phase 5 in [multitenancy.md](../features/multitenancy.md)

## Problem

Ein Kunde ruft an: „bei uns sieht die Klassenlehrerin die Klasse 4a nicht". Um
das zu beantworten, muss jemand von Vita Brevis **sehen, was der Kunde sieht**.
Heute gibt es dafür zwei Wege, und beide sind falsch:

1. **In die Datenbank.** `psql` in das Kundenschema. Kein Audit, keine Grenze,
   keine Spur — und der Kunde erfährt es nie.
2. **Ein Konto im Verzeichnis des Kunden.** Eine Person von Vita Brevis in
   seinem AD, mit Admin-Rolle. Sie steht dann in seiner Benutzerliste, sie
   läuft im AD-Sync mit, und sie ist dauerhaft — ein Zugang, der bleibt,
   nachdem der Anlass weg ist.

ADR-0013 D6 hat die Richtung schon entschieden: eine signierte, einmalig
einlösbare Assertion aus der Konsole, die die Kunden-API gegen eine befristete
Session tauscht, mit Grund und im Audit des Kunden. Offen war das **Wie** — und
eine Frage, die dort nicht gestellt wurde: *was darf so ein Zugriff?*

## Entscheidung

### D1 · Ein Operator-Zugriff darf **lesen**, und das wird über die HTTP-Methode erzwungen

Eine Operator-Session kommt an jede Leseroute wie ein Kunden-Admin und an
**keine** schreibende: jede Anfrage, die nicht `GET`, `HEAD` oder `OPTIONS` ist,
wird mit 403 abgewiesen. Eine Prüfung, an einer Stelle, für alle Routen — auch
für die, die es nächstes Jahr gibt.

Der naheliegende Entwurf war eine **Ausschlussliste**: Operator darf alles
ausser Passwörter lesen, ausser Benutzer anlegen, ausser … Beim Aufschreiben
dieser Liste kam heraus, wie lang sie ist — sechs Dienste geben einen
Klartext-Passwort heraus (Passwortliste einer Klasse, Zugangsdaten-PDF, drei
Reset-Wege, Benutzeranlage), und jeder neue Endpunkt müsste daran denken. Eine
Liste, die jemand ergänzen muss, ist eine Liste, die eines Tages nicht ergänzt
wird.

Mit der Methodenregel fallen fünf der sechs von selbst weg: sie sind `POST`.
Übrig bleibt **genau eine** Leseroute, die einen Klartext-Passwort zeigt, und
die wird ausdrücklich gesperrt:

| Route | Warum gesperrt |
|---|---|
| `GET /classes/{id}/password-list` | PDF mit den gespeicherten Passwörtern einer Klasse. Der Kunde darf das drucken; der Betreiber hat dort nichts zu suchen. |

**Eine Ausnahme in die andere Richtung:** `POST /auth/logout`. Sie erweitert
nichts — sie erlaubt, früher aufzuhören, und setzt beim Kunden sichtbar
`ended_at`. Ohne sie müsste ein Operator warten, bis die Stunde um ist.

**Der Preis, ausdrücklich:** eine lesende `POST`-Route ist mitgesperrt — die
Vorlagen-Vorschau etwa. Das ist der Preis einer Regel ohne Ausnahmeliste, und
er ist niedriger als der einer Liste mit sechs Einträgen, von denen einer
fehlt.

**Was damit nicht geht:** ein Operator kann einem Kunden nicht „mal schnell"
etwas einrichten. Richtig so — das macht der Kunde selbst, notfalls am
Telefon. Braucht es später einen schreibenden Zugriff, ist das ein eigener
Entscheid mit eigener Sichtbarkeit und nicht eine Zeile in dieser Prüfung.

### D2 · Die Assertion trägt keinen Algorithmus-Namen

Format: `mgop1.<base64url(json)>.<base64url(signatur)>`. Der Präfix `mgop1`
ist die Version, und die Version bestimmt das Verfahren: **Ed25519**, immer.

Kein JWT. Nicht wegen der Bibliotheken, sondern wegen des Feldes `alg`: eine
Signatur, deren Verfahren im signierten Dokument steht, lädt dazu ein, dem
Dokument zu glauben — `alg: none` und die Verwechslung von HMAC mit RSA sind
zwei der bekanntesten Fehlerklassen im Web. Hier steht das Verfahren im
**Code**, und eine künftige Änderung ist ein neuer Präfix.

Inhalt: `jti` (UUID), `tenant` (Slug), `operator` (UPN), `reason`, `ticket`,
`iat`, `exp`. Kein Feld mehr — insbesondere keine Rechte-Angabe: was ein
Operator darf, steht in D1 und nicht in einem Dokument, das die Konsole
ausstellt.

### D3 · Geprüft wird offline, mit einem öffentlichen Schlüssel

Die Konsole hält den **privaten** Schlüssel (`COCKPIT_OPERATOR_SIGNING_KEY`),
die Datenebene den **öffentlichen** (`MAGISTER_OPERATOR_PUBLIC_KEY`). Die
Einlösung fragt die Konsole nicht.

Zwei Gründe, und der zweite wog mehr:

* **Der Anmeldeweg hängt nicht an einer zweiten Maschine.** Eine stehende
  Konsole verhindert keinen Zugriff auf einen Kunden, der gerade ein Problem
  hat — und ein Problem hat er meistens dann, wenn etwas steht.
* **Kein gemeinsames Geheimnis.** Mit einem HMAC-Schlüssel könnte **jede**
  Datenebene Assertions für **jeden** Kunden ausstellen. Bei
  `isolation_mode = database` oder `cluster` sind das verschiedene Maschinen
  (ADR-0013 D3); eine davon zu übernehmen würde damit alle übernehmen.

Ohne hinterlegten öffentlichen Schlüssel gibt es die Einlöseroute **nicht** —
nicht 403, sondern nicht gemountet, dieselbe Linie wie ADR-0017 D1. Eine
Einzelinstallation hat keinen Betreiber ausser dem Kunden selbst und braucht
die Fläche nicht.

### D4 · Das Einlöseprotokoll **ist** die Zugriffsliste

Eine Tabelle im Kundenschema, `operator_accesses`: `jti` als
Primärschlüssel, dazu Operator, Grund, Ticket, Beginn, Ablauf, Session-Id und
Adresse.

Sie leistet beides, und das ist der Punkt:

* **Einmal-Einlösung.** Der Primärschlüssel auf `jti` weist die zweite
  Einlösung ab — nicht „meistens", sondern durch Postgres, auch bei zwei
  Anfragen in derselben Millisekunde.
* **Die Liste für den Kunden.** Dieselben Zeilen sind die Antwort auf „wann war
  Vita Brevis bei uns drin, und warum".

Ein separater Nonce-Speicher mit Verfall wäre die üblichere Bauart und hier
schlechter: verfallene Einträge würden gelöscht, und damit wäre eine alte
Assertion irgendwann **wieder** einlösbar. So ist ein `jti` für immer
verbraucht — und die Historie bleibt, weil der Kunde sie sehen soll.

### D5 · Der Operator ist kein Benutzer des Kunden

Die Session trägt `auth_kind = "operator"` und den UPN des Operators in
eigenen Spalten. Es entsteht **keine** Zeile in `ad_user_cache` und **keine**
Rollenzuweisung.

Der bequeme Weg wäre ein Schattenkonto gewesen: dann funktioniert die
bestehende Auflösung aus Verzeichnis und Rollen unverändert. Und dann steht
eine Person von Vita Brevis in der Benutzerliste des Kunden, im Export, im
AD-Sync — und bleibt dort, wenn der Zugriff abgelaufen ist. Ein Zugriff, der
Spuren in den Personendaten des Kunden hinterlässt, ist kein befristeter
Zugriff.

Für die Reichweite gilt: der Operator sieht **alle** Standorte des Kunden
(`ScopeContext.is_admin`), denn ein Support-Fall kennt keine Standortgrenze.
Dass daraus kein Schreibrecht wird, leistet D1 — nicht eine Rechteprüfung, die
man vergessen kann.

### D6 · Sichtbar heisst: während des Zugriffs und danach

Drei Stellen, und die erste ist die wichtigste:

1. **Ein Balken im Frontend des Kunden**, während eine Operator-Session läuft —
   sichtbar für **jeden** angemeldeten Benutzer des Kunden, nicht nur für
   Admins. Wer arbeitet, während jemand zuschaut, soll das sehen und nicht
   nachlesen müssen.
2. **Eine Liste**, die jeder Benutzer aufrufen kann: wer, wann, wie lange,
   warum.
3. **Zwei Audit-Ereignisse** im Protokoll des Kunden:
   `operator_access_started` und `operator_access_ended`.

Der Balken ist ausdrücklich nicht auf Admins beschränkt. Eine Transparenz, die
nur derjenige sieht, der den Zugriff ohnehin bewilligt hätte, ist keine.

### D7 · Grund oder Ticket ist Pflicht, und zwar bei der Ausstellung

Die Konsole stellt ohne Begründung keine Assertion aus (mindestens zehn
Zeichen, damit „test" und „x" nicht durchgehen). Der Grund reist in der
signierten Assertion mit und landet unverändert im Protokoll des Kunden — er
kann auf dem Weg nicht geändert werden, auch nicht von der Datenebene.

## Folgen

**Gut:**

- Ein Support-Fall lässt sich ansehen, ohne `psql` und ohne ein Konto, das
  bleibt.
- Der Kunde sieht jeden Zugriff, während er läuft und danach, mit Grund.
- Eine abgelaufene oder zweimal eingelöste Assertion wird abgewiesen — durch
  einen Primärschlüssel und eine Zeitprüfung, nicht durch Sorgfalt.
- Nichts vom Zugriff steht in den Personendaten des Kunden.
- Kein Schreibweg: die Frage „was hat der Operator geändert?" hat immer die
  Antwort „nichts".

**Preis:**

- Lesende `POST`-Routen (Vorschauen) sind für einen Operator gesperrt.
- Ein Schlüsselpaar mehr im Betrieb. Es gehört in das Zeremonie-Protokoll und
  in den Wiederherstellungsplan: ohne den privaten Schlüssel gibt es keinen
  Operator-Zugriff mehr (kein Datenverlust, aber ein Handgriff).
- Die Liste der Zugriffe wächst unbegrenzt. Bei einem Zugriff pro Woche und
  Kunde sind das fünfzig Zeilen im Jahr; ein Aufräumen wäre hier das falsche
  Sparen.

## Verworfen

**Ausschlussliste statt Methodenregel.** Siehe D1: sechs Einträge, und der
siebte fehlt.

**Schreibrecht mit zweitem Faktor beim Kunden** („der Kunde bestätigt den
Zugriff in seiner Oberfläche"). Richtig gedacht und hier zu früh: es verlangt,
dass zum Zeitpunkt des Support-Falls jemand beim Kunden am Bildschirm sitzt.
Der Fall, in dem das nicht so ist, ist genau der, in dem man gerufen wird.

**Session direkt aus der Konsole.** Die Konsole stellt kein Kunden-Cookie aus
(ADR-0013 D6). Sie hat zum Kundenschema keinen Zugang, und die Session gehört
dorthin, wo sie geprüft wird.

**Assertion als JWT.** Siehe D2.
