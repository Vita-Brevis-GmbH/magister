# Offene Entscheide

Stand 2026-09-09. Jeder Punkt ist so aufgeschrieben, dass er **entschieden
werden kann**: was genau zur Wahl steht, was es kostet, was passiert, wenn wir
nicht entscheiden, und eine Empfehlung. Keine offenen Fragen ohne Optionen.

Reihenfolge nach Dringlichkeit, nicht nach Aufwand.

---

## E17 · Cluster-PITR: wohin gehen die WAL-Dateien?

**Was zur Wahl steht.** ADR-0016 D1 verlangt zwei Ebenen. Ebene 2 (logische
Dumps pro Kunde) steht. Ebene 1 — kontinuierliche WAL-Archivierung plus
Basebackup — fehlt vollständig. Zu entscheiden ist, **wohin die WAL-Dateien
geschrieben werden**; das Werkzeug (pgBackRest) folgt daraus.

| | A: derselbe Share | B: eigener Backup-Host | C: Objektspeicher (S3-kompatibel) |
|---|---|---|---|
| Aufwand einmalig | ~1 Tag | ~3 Tage | ~2 Tage |
| Kosten laufend | 0 (Share existiert) | ~1 VM | ~20–60 CHF/Monat |
| Platz | 5–15 GB/Tag WAL bei aktivem Betrieb | dito | dito |
| Ransomware-Schutz | schwach: derselbe Share, dieselben Rechte | mittel: eigenes Konto, eigene Maschine | stark: Object Lock möglich |
| Zweiter Anbieter | nein | nein | **ja** |
| Wiederherstellung geübt | mit dem bestehenden Backup-Host-Ablauf | dito | neues Verfahren |

**Was es kostet, nicht zu entscheiden.** Die Zusage an einen Kunden bleibt
„jeder Stand der letzten 10 Tage, in Nachtgranularität". Kein Weg auf „gestern
14:37", kein Weg zurück nach einer beschädigten Datenbank ausser dem Dump von
heute Nacht. Bei einem Datenbankschaden um 16:00 ist ein Arbeitstag aller
Kunden verloren — das ist der Fall, den Ebene 2 ausdrücklich nicht abdeckt.

**Empfehlung: B.** Der Backup-Host existiert konzeptionell schon (dort liegt
der private age-Schlüssel, dort läuft die Prüf-Wiederherstellung), er ist im
Runbook, und die Trennung „Anwendungsserver schreibt, Backup-Host verwahrt"
ist dieselbe, die wir bei Ebene 2 bewusst gewählt haben. A verletzt genau die
Eigenschaft, für die wir bei den Dumps das Löschrecht getrennt haben. C wäre
technisch am stärksten, bringt aber einen zweiten Anbieter und ein zweites
Betriebsverfahren — dasselbe Argument, mit dem wir bei E13 gegen
Objektspeicher entschieden haben.

**Entscheidung nötig:** A, B oder C.

---

## E18 · Code-Signing für MSI und `.deb`

**Was zur Wahl steht.** Beide Pakete sind unsigniert. Windows zeigt beim MSI
eine SmartScreen-Warnung; unter AppLocker oder WDAC lässt es sich gar nicht
installieren. Für ein `apt`-Repository fehlt ein GPG-Schlüssel.

| | A: nichts tun | B: nur GPG (`apt`) | C: beides |
|---|---|---|---|
| Kosten einmalig | 0 | 0 | ~400–700 CHF (HSM/Token) |
| Kosten jährlich | 0 | 0 | ~300–600 CHF (OV/EV-Zertifikat) |
| Aufwand | 0 | ~1 Tag (reprepro/aptly) | ~3 Tage |
| Windows-Kunden | Warnung bei jeder Installation; AppLocker blockiert | unverändert | sauber |
| Automatische Updates (E10) | nein | **ja**, für Linux | ja, für beide |

**Was es kostet, nicht zu entscheiden.** Jede Windows-Installation braucht eine
Erklärung („diese Warnung ist normal"), was bei einer Gemeinde-IT Vertrauen
kostet und bei einer mit AppLocker die Installation verhindert. Und ohne
Repository gibt es keine automatische Aktualisierung des Agenten — jedes
Update ist ein Termin.

Seit Juni 2023 verlangen die CAs für Code-Signing eine Hardware-Verwahrung.
Das ist derselbe Verwahrungsvorgang wie beim Plattform-CA-Schlüssel, also kein
neues Verfahren — aber ein zweiter Gegenstand im Tresor.

**Empfehlung: C, in zwei Schritten.** Zuerst B (kostenlos, löst die
Update-Frage für Linux), dann das Windows-Zertifikat, sobald der erste Kunde
mit AppLocker kommt oder mehr als zwei Windows-Installationen anstehen.

**Entscheidung nötig:** A, B oder C — und bei C, ob jetzt oder beim ersten
Bedarf.

---

## E19 · Wo lebt das Protokoll der CA-Zeremonie?

**Was zur Wahl steht.** `scripts/platform-ca-ceremony.sh` schreibt eine
`PROTOKOLL.md` (Zeitpunkte, Fingerprints, Anwesende, Prüfschritte). Sie liegt
heute auf dem USB-Stick im Tresor — also am selben Ort wie der Schlüssel, den
sie beschreibt.

| | A: nur auf dem Stick | B: Stick + Git | C: Stick + Git + Papier im Tresor |
|---|---|---|---|
| Nachvollziehbar ohne Tresorgang | nein | ja | ja |
| Bei Verlust beider Sticks | Protokoll auch weg | Protokoll da | Protokoll da |
| Enthält Geheimnisse | nein (nur Fingerprints und Zeiten) | nein | nein |
| Aufwand | 0 | 5 Minuten je Zeremonie | 15 Minuten |

**Was es kostet, nicht zu entscheiden.** Wer in zwei Jahren fragt „welcher
Schlüssel hat dieses Intermediate ausgestellt und wer war dabei", muss in den
Tresor. Bei einem Audit oder einem Vorfall ist das genau der Moment, in dem
man es nicht will. Und gehen beide Sticks verloren, ist mit dem Schlüssel auch
der Nachweis weg, dass es je eine Zeremonie gab.

**Empfehlung: B.** Das Protokoll enthält keine Geheimnisse — nur Fingerprints,
Zeitpunkte und Namen. Es gehört ins Repository unter `docs/ca/`, wo es
versioniert und ohne Tresorgang lesbar ist. C ist die Variante für eine
Zertifizierung; wenn keine ansteht, ist es Papier ohne Zweck.

**Entscheidung nötig:** A, B oder C.

---

## E20 · Dedizierte Offline-Maschine für die CA-Zeremonie?

**Was zur Wahl steht.** Die Zeremonie erzeugt den Root-Schlüssel auf einer
Maschine ohne Netz. Zu entscheiden ist, ob das ein **eigenes Gerät** ist oder
ein bestehender Rechner, der für die Zeremonie vom Netz genommen wird.

| | A: bestehender Laptop, Live-System vom Stick | B: dedizierter Mini-PC, nur dafür |
|---|---|---|
| Kosten | 0 | ~250–400 CHF einmalig |
| Aufwand je Zeremonie | ~30 Minuten (booten, prüfen) | ~10 Minuten |
| Risiko | Firmware/Hardware hat schon anderes gesehen | Gerät hat nie etwas anderes getan |
| Aufbewahrung | keine | ein Gerät mehr im Tresor |
| Prüfbarkeit | Live-System-Hash prüfbar, Hardware nicht | beides |

**Was es kostet, nicht zu entscheiden.** Die nächste Zeremonie (das erste
echte Connector-Intermediate) wartet darauf. Solange sie nicht gelaufen ist,
lässt sich **kein Agent mit einem echten Zertifikat anmelden** — der Kanal
funktioniert nur mit Test-CA. Das blockiert den ersten gehosteten Kunden.

**Empfehlung: A, mit einem Live-System, dessen Hash im Protokoll steht.** Der
Root-Schlüssel liegt nach der Zeremonie verschlüsselt auf zwei Sticks und wird
alle paar Jahre gebraucht; ein Gerät, das dafür 250 CHF kostet und drei Jahre
im Schrank liegt, ist teurer als der Gewinn. Wenn später eine Zertifizierung
ein dediziertes Gerät verlangt, ist der Wechsel eine Beschaffung und kein
Umbau.

**Entscheidung nötig:** A oder B. Danach kann die Zeremonie terminiert werden.

---

## E21 · Entra-App-Registrierung für die Konsolen-Anmeldung

**Was zur Wahl steht.** Die Konsole hat heute nur den Bootstrap-Token. Für die
Anmeldung mit Hardware-Schlüssel braucht sie eine App-Registrierung in **Ihrem**
Entra-Tenant. Das kann ich nicht selbst tun — es ist ein Vorgang in Ihrem
Verzeichnis.

Konkret gebraucht:

1. App-Registrierung „Magister Konsole", Single-Tenant.
2. Redirect-URI: `https://<management-adresse>:4444/auth/callback`.
3. Client-Secret oder Zertifikat (Zertifikat ist besser, hält länger).
4. Eine Conditional-Access-Regel, die für diese App **phishing-resistente MFA**
   verlangt — also FIDO2-Schlüssel oder Passkey, nicht SMS und nicht die
   Authenticator-App mit Zahleneingabe.
5. Eine Sicherheitsgruppe für die berechtigten Personen (heute: Sie und Rolf).

**Was es kostet, nicht zu entscheiden.** Die Konsole bleibt bei einem
Bootstrap-Token als einzigem Zugang. Ein Token ist ein Geheimnis, das kopiert
werden kann, ohne dass es jemand merkt — und die Konsole kann Sitzungen in
**jeden** Kunden ausstellen. Das ist der höchstwertige Zugang im ganzen
System.

**Empfehlung:** machen, bevor der erste Fremdkunde produktiv geht. Bis dahin
ist der Token vertretbar, weil nur wir beide Zugang zur Management-Adresse
haben; mit dem ersten Kundendatensatz eines Dritten ist er es nicht mehr.

**Von Ihnen gebraucht:** die fünf Punkte oben, dann trage ich Issuer, Client-Id
und Redirect-URI ein.

---

## Bereits entschieden (zur Vollständigkeit)

| Nr. | Entscheid | Stand |
|---|---|---|
| E9 | Schlüsselhalter Plattform-CA: Hadorn und Straubhaar, zwei USB-Sticks im Tresor, Passphrasen bei den Haltern | ✅ 2026-09-08 |
| E10 | Automatische Agenten-Updates | ⏳ hängt an E18 (Repository) |
| E11 | Kein Rückfall auf 443 für den Connector-Kanal | ✅ |
| E13 | Lokaler Share statt Objektspeicher für die Dumps | ✅ |
| E14 | 10 Tage Aufbewahrung | ✅ |
| E15 | Zwölf Monatskopien | ✅ 2026-09-09, umgesetzt |
| E16 | Kunden-Admin für mehrere Kunden: über Rollen je Kunde, nicht über einen Über-Mandanten | ✅ |
