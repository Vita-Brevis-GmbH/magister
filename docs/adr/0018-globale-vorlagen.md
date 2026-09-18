# ADR-0018 · Globale Vorlagen gehören der Konsole, der Text des Kunden ihm

**Status:** angenommen, 2026-09-10
**Kontext:** [ADR-0009](0009-mail-aliase-templates-namensaenderung.md) (Vorlagen
je `key`/Sprache/Standort), [ADR-0013](0013-mandantenfaehigkeit-control-plane.md)
(Steuerebene), [ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md)
(Soll-Zustand und Abgleich), Phase 4 in [multitenancy.md](../features/multitenancy.md)

## Problem

Ein Schulträger, der Magister neu bekommt, startet heute mit **leeren
Vorlagen**: die eingebauten Jinja-Vorlagen drucken korrekte, aber nackte
Briefe. Wer etwas anderes will, schreibt Betreff und Rumpf selbst — in vier
Sprachen, für drei Schlüssel, pro Standort. Beim ersten Kunden hat das jemand
von Hand gemacht. Beim zehnten ist es zehnmal dieselbe Arbeit, und die
Fassungen laufen auseinander.

Was fehlt, ist eine Vorlage, die der **Betreiber** pflegt und alle Kunden
bekommen — und zwar so, dass drei Dinge gleichzeitig wahr bleiben:

1. **Ein Kunde, der seinen eigenen Text geschrieben hat, behält ihn.** Ein
   Rollout, der über gewachsene Texte fährt, wird einmal gemacht und danach
   nie wieder benutzt.
2. **Drucken hängt nicht an der Konsole.** Ein Elternbrief am Montagmorgen
   darf nicht daran scheitern, dass die Steuerebene gerade neu startet.
3. **Manche Vorlagen sind nicht verhandelbar.** Eine Datenschutzerklärung oder
   ein Passwort-Übergabeblatt mit rechtlichem Text soll der Kunde *nicht*
   umschreiben können.

Die drei Punkte widersprechen sich nur scheinbar. Sie ergeben zusammen einen
Entwurf, der von einem naiven „globale Vorlagen in eine Tabelle" deutlich
abweicht.

## Entscheidung

### D1 · Vorlagen reisen im Soll-Zustand — im selben Kanal, in derselben Richtung

Globale Vorlagen kommen über `GET /api/tenants/{id}/desired-state`, den
ADR-0017 D3 schon gebaut hat: die Datenebene **holt**, die Konsole schiebt
nicht, und der Abgleich schreibt nur die Differenz.

Kein zweiter Kanal, kein Push, kein „die Konsole schreibt in das Kundenschema".
Die Konsole hat keinen Datenbankzugang zum Kunden (ADR-0013), und das ist der
Grund, aus dem ein Einbruch in die Konsole nicht auch ein Einbruch in jeden
Kunden ist. Ein Rollout, der diesen Weg abkürzt, gibt die Eigenschaft auf.

Die abgeholten Vorlagen werden im Kundenschema **materialisiert**. Damit ist
Punkt 2 des Problems keine Zusage, sondern eine Folge der Bauart: der Renderer
liest eine lokale Tabelle und weiss nicht, ob die Konsole überhaupt läuft.

### D2 · Zwei Tabellen, nicht eine mit einem Herkunfts-Flag

Im Kundenschema stehen die Vorlagen der Plattform in einer **eigenen** Tabelle
(`platform_document_templates`), getrennt von den eigenen Vorlagen des Kunden
(`document_templates`, unverändert).

Der naheliegende Entwurf wäre eine Tabelle mit `origin ∈ {local, platform}`
gewesen. Er scheitert an Punkt 1: sobald beide Fassungen um dieselbe Zeile
konkurrieren, muss der Abgleich entscheiden, welche er überschreibt — und jede
Antwort ist irgendwann die falsche. Mit zwei Tabellen kann er die Frage nicht
stellen: er schreibt **ausschliesslich** in die Plattform-Tabelle, und dass die
eigene Fassung des Kunden unangetastet bleibt, ist keine Sorgfalt, sondern
Bauart.

Nebeneffekt, der den Hinweis in D4 überhaupt möglich macht: beide Fassungen
liegen gleichzeitig vor. „Es gibt eine neue globale Fassung" ist ein Vergleich
und keine Vermutung.

### D3 · `tenant_may_override = false` kehrt den Vorrang um — es löscht nichts

Eine gesperrte Vorlage gewinnt gegen die eigene Fassung des Kunden. Sie
**löscht sie nicht**.

Die Auflösungskette, von oben nach unten:

| # | Fassung | gilt, wenn |
|---|---------|-----------|
| 1 | Plattform, gesperrt | eine Plattformvorlage mit `may_override = false` existiert |
| 2 | Kunde, Standort | der Kunde für diesen Standort eine aktive Fassung hat |
| 3 | Kunde, global | der Kunde eine aktive Fassung ohne Standort hat |
| 4 | Plattform, freigegeben | eine Plattformvorlage existiert |
| 5 | eingebaut | sonst |

Warum nicht löschen: eine Sperre kann zurückgenommen werden — durch einen
Entscheid, durch einen Tippfehler in der Zielgruppe, durch einen Kunden, der
das Modul kauft. Wird die Sperre gelöst, soll der Text des Kunden wieder da
sein. Ein `DELETE` im Namen einer Richtlinie ist ein Datenverlust, den niemand
angeordnet hat.

Die Oberfläche zeigt die eigene Fassung in diesem Fall weiterhin an — als
„liegt bereit, gilt derzeit nicht". Ein verschwundener Text ist ein Fehlerbild;
ein sichtbarer, erklärt inaktiver Text ist eine Information.

### D4 · Der Hinweis braucht eine Version und eine Quittung

Jede Plattformvorlage trägt eine `version`, die **nur bei einer inhaltlichen
Änderung** steigt (Betreff, Rumpf, Sperre). Eine Änderung der Zielgruppe ändert,
*wer* sie bekommt, nicht *was* sie sagt — sie bumpt nicht.

Der Kunde mit eigener Fassung sieht „neue globale Fassung verfügbar", solange
`platform_document_templates.version > document_templates.platform_version_ack`.
Die Quittung ist ein ausdrücklicher Klick und kein Nebeneffekt des Speicherns:
wer seinen Text bearbeitet, hat damit nicht gesagt, dass er den neuen gesehen
hat.

Ohne Quittung gäbe es nur zwei Möglichkeiten, und beide sind schlecht: der
Hinweis steht für immer da (und wird zur Tapete), oder er verschwindet beim
nächsten Speichern (und niemand hat die neue Fassung gelesen).

### D5 · Die Zielgruppe löst die Konsole auf, nicht der Kunde

Eine Plattformvorlage richtet sich an **alle** Kunden, an ein **Profil**
(`school` oder `company`) oder an eine **Auswahl**. Welche Vorlagen für einen
Kunden gelten, entscheidet die Konsole; im Soll-Zustand steht nur das Ergebnis.

Der Kunde erfährt damit nicht, dass es andere Zielgruppen, andere Profile oder
andere Kunden gibt. Dieselbe Linie wie bei der Registry (ADR-0013): jeder
Mandant sieht seinen Eintrag und nicht die Liste.

### D6 · Die gelieferte Menge ist vollständig — Fehlen heisst „keine Aussage"

Steht `templates` im Soll-Zustand, ist die Liste **vollständig**: was nicht
darin steht, wird im Kundenschema entfernt. Nur so kann eine Vorlage
zurückgezogen werden.

Fehlt der Schlüssel ganz, ist das **keine Aussage** und es wird nichts
angefasst — dieselbe Unterscheidung wie bei der Rechte-Matrix in ADR-0017,
und aus demselben Grund: eine Konsole, die nach einem Fehler ein leeres
Dokument liefert, darf nicht alle Kunden leerräumen. Der Unterschied liegt in
`null` gegen `[]`, und er ist im Abholer geprüft, nicht im Aufrufer geregelt.

### D7 · Was sich nicht rendern lässt, wird nicht ausgeliefert

Der Abgleich rendert jede gelieferte Vorlage gegen den Beispielkontext, bevor
er sie materialisiert. Was scheitert, wird **abgewiesen**: nicht geschrieben,
im Log als Fehler benannt, und eine bereits vorhandene brauchbare Fassung
bleibt stehen.

Nachträglich hinzugekommen, aus einem Test: der erste Entwurf materialisierte
alles, und eine Vorlage mit einem Platzhalter, den es nicht gibt, liess den
Brief in einer Ausnahme enden. Der erste Ort, an dem der Tippfehler aufgefallen
wäre, war damit der **Drucker eines Kunden**. Die Konsole kann die Prüfung
nicht übernehmen — sie kennt den Kontext eines Briefes nicht —, also gehört sie
in den Abgleich. Es ist dieselbe Prüfung, die `DocumentTemplateService.save()`
für die eigene Fassung des Kunden schon macht.

**Kein Audit-Ereignis für eine Abweisung.** Der Befund gehört dem Betreiber,
und die Konsole liefert die kaputte Vorlage bei jedem Lauf wieder — ein
Ereignis daraus stünde alle fünf Minuten im Protokoll des Kunden, für einen
Fehler, den er nicht beheben kann.

## Folgen

**Gut:**

- Ein neuer Kunde startet mit brauchbaren Texten, ohne dass jemand sie tippt.
- Rechtlich verbindlicher Text ist erzwingbar, ohne dem Kunden etwas
  wegzunehmen, was er behalten dürfte.
- Drucken funktioniert bei stehender Konsole; der Abgleich holt nach, was
  liegen blieb.
- Der Abgleich ist idempotent: derselbe Soll-Zustand schreibt beim zweiten Lauf
  nichts und protokolliert nichts.
- Eine unbrauchbare Vorlage kostet den Kunden nichts: sie kommt nicht an, und
  gedruckt wird mit dem letzten guten Stand.

**Preis:**

- Zwei Tabellen für einen Begriff. Wer „die Vorlage" sucht, muss wissen, dass es
  zwei Orte gibt; die Auflösungskette steht deshalb in D3 als Tabelle und im
  Code als eine Funktion, nicht verstreut.
- Der Hinweis braucht eine dritte Spalte (`platform_version_ack`) und einen
  Endpunkt, der nichts tut als quittieren.
- Eine Einzelinstallation bekommt von D1 bis D6 nichts: ohne Konsole gibt es
  keine Plattformvorlagen, die Kette beginnt bei Stufe 2. Das ist gewollt
  (ADR-0016 D9), heisst aber, dass die Kette in zwei Betriebsarten geprüft
  werden muss.

## Verworfen

**Rollout als Kopie in die Kundentabelle.** Die Konsole schreibt beim Rollout
die Vorlage als Zeile des Kunden. Einfacher — und genau der Entwurf, der Punkt 1
verletzt: die zweite Auslieferung überschreibt, was der Kunde inzwischen
geändert hat, oder sie überschreibt nichts und der Rollout wirkt nur beim ersten
Mal. Beides ist als Verhalten nicht erklärbar.

**Vorlagen live aus der Konsole rendern.** Immer aktuell, kein Abgleich, keine
Version. Und ein Elternbrief, der scheitert, weil die Steuerebene neu startet.
Verworfen an Punkt 2.

**`may_override` als Eigenschaft des Kunden statt der Vorlage.** „Dieser Kunde
darf nichts überschreiben" wäre weniger Datenmodell. Aber die Sperre gehört zum
*Text* — sie ist rechtlich begründet und nicht kundenspezifisch —, und ein
Kunde, dem man alles sperrt, verliert auch die Vorlagen, an denen niemand ein
Interesse hat.

**Version aus einem Hash des Inhalts.** Spart die Zählung, und der Vergleich
„neuer als quittiert" wird unmöglich: ein Hash ist ungleich, aber nicht grösser.
