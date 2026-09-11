# ADR-0022 · Der AD-Abgleich läuft über den Connector

**Status:** angenommen, 2026-09-11
**Kontext:** [ADR-0004](0004-ad-incremental-sync.md) (inkrementeller Abgleich über
`whenChanged`), [ADR-0011](0011-ad-service-boundary-10-container-split.md) (AD-Grenze, eingehender
RPC), [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) D1 (Schema je
Kunde), [ADR-0014](0014-ad-connector-agent.md) (Connector-Agent, Allowlist,
ausgehende Warteschlange), [ADR-0021](0021-betrieb-im-grossen.md) D4 (Fan-out
des Abgleichs je Kunde), Restposten „AD-Sync als Push“ in
`docs/features/multitenancy.md`

## Problem

ADR-0014 sagt zu: der Connector-Agent ist **der einzige Prozess mit AD-Zugang**
bei einem gehosteten Kunden; die Plattform öffnet nie eine Verbindung in sein
Netz. Für Passwort-Reset, Gruppen und Kontosteuerung stimmt das — die sechzehn
Methoden der Allowlist gehen über die Warteschlange.

Für den **Abgleich** stimmt es nicht. Drei Messungen von heute:

1. **`search_users` steht nicht auf der Allowlist** (`magister_api/ad/rpc.py`,
   `cockpit_api/services/connector_queue.py`). `RemoteAdClient` überschreibt die
   Methode deshalb auch nicht — sie wird von `AdClient` geerbt und spricht
   **direkt LDAP**. Bei einem gehosteten Kunden versucht die Plattform damit
   genau die Verbindung, die es nicht geben soll. Sie scheitert am Netz, nicht
   an einer Prüfung; die Zusage aus ADR-0014 hält also aus Versehen.
2. **Der wiederkehrende Abgleich wählt einen anderen Rücken als der
   Anfragepfad.** `get_ad_client` (`routers/admin_sync.py`) entscheidet
   zwischen RPC, Connector und direktem LDAP; der Scheduler
   (`services/ad_sync_scheduler.py`) nimmt fest `AdClient`. Zwei Auswahlpfade
   für dieselbe Frage, und der zweite kennt den Connector gar nicht.
3. **Der wiederkehrende Abgleich läuft immer voll.** Der Scheduler ruft
   `sync_all()` ohne `mode` auf, die Vorgabe ist `"full"`. `last_full_sync_at`
   wird geschrieben und **nie gelesen** — obwohl der Docstring von
   `AdSyncState` seit ADR-0004 sagt, der Scheduler erzwinge darüber den
   periodischen Vollabgleich. Der inkrementelle Weg existiert nur für den
   Admin, der ihn ausdrücklich anklickt.

Punkt 3 ist ohne Connector eine Unhöflichkeit gegenüber dem
Domänencontroller. Mit Connector ist es ein Fehler: das ganze Verzeichnis, alle
fünfzehn Minuten, durch eine Auftragswarteschlange mit 90 Sekunden Frist.

Was **nicht** das Problem ist: der Agent selbst. Er führt `AdClient`-Methoden
aus, `search_users` ist eine davon, und er ist damit fertig, bevor die Frage
der Allowlist überhaupt gestellt wird.

## Entscheidung

### D1 · `search_users` kommt auf die Allowlist — als einzige Methode mit grosser Antwort

Kein neuer Auftragstyp, keine zweite Warteschlange, kein Sonderweg: derselbe
Auftrag wie die sechzehn anderen, mit Allowlist auf beiden Seiten, mit
HMAC-signiertem Ergebnis, mit Frist. Die Nutzlast ist das, was die Methode
ohnehin nimmt (Suchbasis, Attribute, `changed_since`), und das Ergebnis ist
eine Liste von Benutzerdatensätzen.

Was daran neu ist, ist die **Grösse**. Ein Passwort-Reset gibt ein Bool
zurück, ein Abgleich eines Schulträgers ein bis zwei Megabyte JSON. Daraus
folgt Dreierlei, und zwar ausdrücklich statt stillschweigend:

* **Eigene Frist.** Die Standard-Auftragsfrist von 90 Sekunden ist die Zeit,
  die ein Mensch vor einem Formular wartet. Ein Verzeichnislauf ist kein
  Mensch vor einem Formular: für `search_users` gilt eine Frist von zehn
  Minuten, und die Datenebene wartet entsprechend länger auf das Ergebnis.
* **Eigene Obergrenze.** Ein Ergebnis über der Grenze wird **abgewiesen**, mit
  einer Meldung, die sagt, was zu tun ist (engere Suchbasis, inkrementell
  laufen lassen). Nicht abgeschnitten: ein halber Abgleich ist schlimmer als
  keiner, weil er aussieht wie ein ganzer und am Ende Konten als verschwunden
  behandelt, die es noch gibt.
* **Keine Seitenbildung.** Naheliegend wäre, den Lauf in Seiten zu zerlegen.
  Sie hilft nicht: die Seitenmarke von LDAP gehört zu **einer** Verbindung,
  und jeder Auftrag ist eine neue. Eine eigene Seitenbildung über sortierte
  GUID-Bereiche wäre Sortierung im Verzeichnis, mehrere Aufträge je Lauf und
  ein halber Zustand zwischen ihnen. Die Grenze plus D3 lösen dasselbe
  Problem mit einem Bruchteil der Fläche; kommt je ein Kunde über die Grenze,
  ist die Seitenbildung immer noch möglich — dann mit einem echten Fall statt
  einer Vermutung.

### D2 · Ein Rücken für alle Wege

Die Wahl zwischen RPC, Connector und direktem LDAP steht ab jetzt an **einer**
Stelle (`magister_api/ad/factory.py`), und beide Aufrufer — der Anfragepfad
und die Schleife — holen sie sich dort. Ein Contract-Test pinnt es: für
dieselben Einstellungen und denselben Kunden müssen beide denselben Rücken
bauen.

Das ist nicht Kosmetik. Der Fehler oben ist nicht entstanden, weil jemand den
Connector vergessen hat, sondern weil es zwei Stellen gab, an denen man ihn
vergessen konnte. Der dritte Rücken kam mit ADR-0014 dazu; die Schleife ist
älter und wurde nicht mitgezogen. Mit einer Stelle kann das nicht wieder
passieren, und der Test sagt es, bevor es ein Kunde merkt.

### D3 · Der wiederkehrende Lauf ist inkrementell; der volle hat einen Takt

Regel: **inkrementell**, sobald ein Cursor steht. **Voll**, wenn kein Cursor
da ist (erster Lauf, nach einem Zurücksetzen) oder wenn der letzte volle Lauf
länger her ist als `MAGISTER_AD_FULL_SYNC_HOURS` (Vorgabe 24 Stunden).

Beide Hälften sind nötig, und zwar aus gegenläufigen Gründen. Inkrementell,
weil `whenChanged` genau die Änderungen liefert und der Rest Übertragung ohne
Erkenntnis ist. Voll, weil `whenChanged` **Löschungen nicht zeigt**: ein
gelöschtes Konto hat keinen Änderungszeitpunkt mehr, es ist einfach weg. Ein
rein inkrementeller Betrieb würde ein gelöschtes Konto für immer im Cache
behalten — und damit in der Klassenliste.

Vierundzwanzig Stunden und nicht eine Woche (die der alte Docstring nennt):
ein Konto, das gestern ausgetreten ist, soll heute nicht mehr in einer Liste
stehen, aus der jemand ein Passwort zurücksetzt. Wer den Takt anders braucht,
stellt ihn ein; Null heisst „jeder Lauf voll“ und ist der Rückweg auf das
heutige Verhalten.

### D4 · Der Agent kodiert, was er zurückgibt — an einer Stelle

Der Agent liefert heute alles durch `_jsonable()`: Tupel zu Listen, Mengen zu
sortierten Listen, alles andere muss schon JSON-tauglich sein. Ein
`AdUserRecord` ist es nicht (Dataclass mit Zeitstempel), und das Ergebnis
wäre ein Fehler beim Signieren statt beim Kodieren.

Deshalb bekommt der Runner eine Tabelle „Methode → Kodierer“ mit genau einem
Eintrag. Die Umwandlung selbst ist die, die es schon gibt
(`ad_user_record_to_jsonable` aus `magister_api.ad.rpc`) — der Agent hat
`magister-api` ohnehin als Abhängigkeit, und zwei Kodierer für dasselbe
Datenformat wären zwei Stände.

## Folgen

* Ein gehosteter Kunde wird tatsächlich über den Agenten abgeglichen. Vorher
  wäre jeder Abgleich an einer Verbindung gescheitert, die es nicht geben
  darf — täglich, still, mit `ad_sync_failed` im Protokoll.
* Der Abgleich hängt damit für gehostete Kunden an der Erreichbarkeit der
  Konsole. Das ist keine neue Abhängigkeit, sondern dieselbe wie beim
  Passwort-Reset, und sie steht schon im Kopf von `connector_client.py`.
* Die tägliche Übertragung schrumpft auf die Änderungen. Ein Vollabgleich
  bleibt, aber als Takt und nicht als Dauerzustand.
* `last_full_sync_at` wird zum ersten Mal gelesen. Bis heute war es ein Feld,
  das eine Zusage im Docstring trug, die niemand einlöste.
* Die Grenze für die Antwortgrösse ist eine neue Fehlerquelle bei sehr grossen
  Verzeichnissen. Sie ist gewollt: sie meldet sich beim ersten Lauf, mit einer
  Meldung, die den nächsten Schritt nennt — statt beim dreissigsten, als
  halber Datenbestand.

## Verworfen

* **Der Agent schiebt von sich aus (echter Push).** Der Agent hätte den
  Abgleich selbst getaktet und das Ergebnis unaufgefordert geschickt. Damit
  bräuchte die Plattform eine Annahmestelle für unangeforderte Daten, der
  Agent einen eigenen Fahrplan und beide eine Abstimmung, wessen Takt gilt —
  und ADR-0021 D4 hat den Fahrplan gerade erst dorthin gelegt, wo die
  Einstellungen des Kunden stehen. Der Auftrag aus der Warteschlange ist
  derselbe Weg wie alles andere; „Push“ bleibt, dass der Agent von innen
  anklopft.
* **Ein eigener Endpunkt für den Abgleich, an der Warteschlange vorbei.**
  Schneller, ja — und ein zweiter Kanal mit eigener Anmeldung, eigener
  Allowlist-Frage und eigener Signatur. Genau die Vervielfachung, die ADR-0014
  D3 ausschliesst.
* **Seitenbildung von Anfang an.** Siehe D1: mehr Fläche als Nutzen, und der
  Fall, der sie rechtfertigt, ist noch keinem Kunden begegnet.
* **Den Vollabgleich ganz streichen und Löschungen über Tombstones lesen.**
  Verlangt Zugriff auf den `Deleted Objects`-Container, also mehr Rechte für
  das Dienstkonto, als Magister sonst braucht. Ein Vollabgleich pro Tag kostet
  weniger.
