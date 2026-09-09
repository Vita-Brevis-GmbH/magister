# Windows-Paket des Connector-Agenten

Ergebnis: `magister-connector-<version>-x64.msi` — ein Paket, das ein
Gemeinde-IT-Verantwortlicher doppelklicken oder per GPO verteilen kann.

## Warum der Bau zweigeteilt ist

| Schritt | Wo | Werkzeug | Warum dort |
|---|---|---|---|
| 1. Payload (Agent + Python-Laufzeit einfrieren) | **Windows** | PyInstaller | PyInstaller friert die Laufzeit ein, auf der es selbst läuft. Es kann nicht für eine fremde Plattform bauen. |
| 2. MSI drumherum | **Linux** | `wixl` (msitools) | Der Paketbau läuft damit auf derselben Maschine wie alles andere, und die WiX-Quelle ist auf dem Entwicklerrechner prüfbar — mit `--stub` sogar ohne Windows. |

Der zweite Schritt könnte auch unter Windows mit dem WiX Toolset laufen. Gegen
diese Variante spricht, dass dann **kein** Teil des Pakets ausserhalb einer
Windows-Umgebung überprüfbar wäre — und eine WiX-Quelle, die man nur in CI
bauen kann, ist eine Quelle, an der niemand gern etwas ändert.

## Bauen

### Ganz, wie CI es tut

```bash
# --- unter Windows ---
cd agent
uv sync --extra packaging
uv run pyinstaller --clean --noconfirm packaging/windows/magister-connector.spec
copy deploy\config.example.json dist\magister-connector\
copy packaging\windows\INSTALL.txt dist\magister-connector\

# --- unter Linux, mit dist/magister-connector/ aus dem Windows-Lauf ---
apt-get install wixl
agent/packaging/windows/build-msi.sh dist/magister-connector magister-connector-0.1.0-x64.msi
```

### Nur die WiX-Quelle prüfen, ohne Windows

```bash
agent/packaging/windows/build-msi.sh --stub
```

Baut ein installierbares MSI mit Platzhalter-Inhalt. Der Zweck ist die
**Struktur**: Dienst-Einträge, Zielverzeichnisse, Verknüpfungen, Registry,
Startbedingungen. Das Ergebnis heisst `magister-connector-STUB.msi` und ist
zum Installieren ausdrücklich nicht gedacht.

Prüfen, was drin ist:

```bash
msiinfo tables magister-connector-STUB.msi
msiinfo export magister-connector-STUB.msi ServiceInstall
msiinfo export magister-connector-STUB.msi Directory
```

## Was das MSI tut — und was ausdrücklich nicht

**Es installiert:**

* `%ProgramFiles%\Magister Connector\` — der eingefrorene Agent, zwei
  Programme: `magister-connector.exe` (enroll, run, check) und
  `magister-connector-service.exe` (der Dienst).
* Den Dienst `MagisterConnector`, Starttyp **Automatisch**, Konto
  **LocalSystem**.
* `%ProgramData%\Magister Connector\config.example.json` als Vorlage.
* Startmenü-Einträge: eine Eingabeaufforderung im Installationsordner und die
  Anleitung.
* `HKLM\Software\Vita Brevis\Magister Connector` mit den beiden Pfaden und der
  Version — für die Fehlersuche und für Verteilungswerkzeuge.

**Es tut ausdrücklich nicht:**

* **Den Dienst starten.** Zum Installationszeitpunkt ist der Agent nicht
  angemeldet; er hat kein Zertifikat und keinen API-Key. Ein Start würde nur
  eine Fehlermeldung ins Ereignisprotokoll schreiben. Nach `enroll` startet
  ihn der Betreiber einmal, danach kommt er bei jedem Neustart mit.
* **Nach dem Einmal-Token fragen.** Ein Token in einer MSI-Eigenschaft steht
  in der Kommandozeile des Installers und damit im Ereignisprotokoll und in
  jedem Verteilungswerkzeug. Es gehört über stdin in `enroll`.
* **Eine `config.json` schreiben.** Nur die Vorlage wird installiert. Damit
  überschreibt ein Update nie eine funktionierende Konfiguration — der mit
  Abstand häufigste Paketfehler.
* **Die Rechte des Zustandsverzeichnisses setzen.** Das macht der Agent
  selbst (`connector_agent.winsec.harden_directory`), siehe unten.

## Die Rechte setzt der Agent, nicht das Paket

Im Zustandsverzeichnis liegt der private Schlüssel des Agenten. Er ist mit dem
Zertifikat die eine Hälfte seiner Authentisierung gegenüber der Plattform; wer
ihn und den API-Key hat, kann als dieser Agent AD-Aufträge annehmen.

Das Abdichten macht deshalb der **Agent** beim Anlegen des Verzeichnisses und
nicht das Installationsprogramm. Der Grund ist nicht Bequemlichkeit: ein
Sicherheitsmerkmal, das nur die MSI setzt, fehlt genau bei der Installation,
die jemand „schnell zum Testen" von Hand gemacht hat und die dann drei Jahre
läuft. So gilt es für jede Installationsart gleich — MSI, Handinstallation,
ausgepacktes Archiv.

Gesetzt wird mit `icacls` und **SIDs**:

```
icacls "%ProgramData%\Magister Connector" /inheritance:r ^
    /grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F
```

SIDs und nicht Namen, weil `icacls` lokalisierte Kontonamen nimmt und
`BUILTIN\Administrators` auf einem deutschen Windows nicht existiert.
`/inheritance:r` ist der wichtige Teil: ohne es behält `%ProgramData%` sein
Leserecht für „Benutzer", und auf einem Mitgliedsserver ist das jeder
angemeldete Domänenbenutzer.

**Geprüft** wird bei jedem Start, und der Agent läuft nicht, wenn die Prüfung
scheitert. Nicht über `icacls` (dessen Ausgabe ist lokalisiert), sondern über
die DACL als SDDL — dort stehen die Treuhänder als SID oder als
sprachunabhängige Kurzform. Siehe `connector_agent/winsec.py`; die Zerlegung
ist in `tests/test_winsec.py` vollständig geprüft.

Der naheliegende Weg wäre gewesen, die POSIX-Prüfung unter Windows einfach zu
überspringen. Das wäre die schlechteste der Möglichkeiten: `os.stat()` liefert
dort erfundene Modus-Bits (Verzeichnisse melden `0o777`), die POSIX-Prüfung
schlägt also **immer** fehl und der Dienst startete nie — und sie stumm zu
überspringen hiesse, den Agenten laufen zu lassen und die Zusage über seinen
privaten Schlüssel unbelegt zu lassen.

## Signieren

Das MSI ist **unsigniert**. Windows zeigt beim Ausführen eine
SmartScreen-Warnung, und in Umgebungen mit AppLocker oder WDAC lässt es sich
ohne Signatur nicht installieren.

Zum Signieren braucht es ein Code-Signing-Zertifikat (EV oder ein
OV-Zertifikat auf einem HSM — seit Juni 2023 verlangen die CAs eine
Hardware-Verwahrung) und `signtool` oder `osslsigncode`:

```bash
osslsigncode sign -pkcs11module … -certs code-signing.pem \
    -t http://timestamp.digicert.com \
    -in magister-connector-0.1.0-x64.msi \
    -out magister-connector-0.1.0-x64-signed.msi
```

Ein Zeitstempel (`-t`) ist Pflicht: ohne ihn wird die Signatur mit dem Ablauf
des Zertifikats ungültig, und dann bricht eine Installation, die zwei Jahre
lang funktioniert hat.

Das Zertifikat gibt es noch nicht — das ist eine Beschaffung mit Kosten und
mit einer Verwahrungsfrage (dasselbe Thema wie beim Plattform-CA-Schlüssel,
siehe `docs/runbooks/platform-ca.md`). Bis dahin wird das MSI per GPO oder
Intune verteilt, wo die SmartScreen-Warnung nicht auftritt, oder von Hand mit
einer erklärten Warnung.

## Kleinigkeiten, die auffallen

* **Die Installer-Sprache im MSI steht auf 1033 (Englisch)**, obwohl die
  Produktsprache 1031 ist: `wixl` schreibt die Zusammenfassungs-Vorlage
  fest. Das Paket hat keine eigene Oberfläche — alle sichtbaren Texte
  (Produktname, Beschreibung, Startbedingungen, `INSTALL.txt`) sind deutsch —,
  deshalb bleibt es dabei.
* **Zwei Verzeichniseinträge mit `Name="."` unter `INSTALLDIR`.** Das ist
  MSI-Semantik für „dasselbe Verzeichnis wie das übergeordnete" und kein
  Fehler; `wixl-heat` erzeugt je Durchlauf einen.
* **`Permanent="yes"` kennt wixl nicht** und verwirft es stillschweigend.
  Gebraucht wird es nicht: es gibt bewusst kein `RemoveFolder` auf dem
  Zustandsverzeichnis, und Windows entfernt ein Verzeichnis nur, wenn es leer
  ist. `build-msi.sh` bricht bei solchen wixl-Warnungen ab, damit nicht
  irgendwann ein ganzes `ServiceInstall` verschwindet, ohne dass es auffällt.

## Noch offen

* **`.deb` für Debian/Ubuntu.** Die systemd-Unit liegt in
  `agent/deploy/magister-connector.service`; ein Paket drumherum fehlt.
* **Automatische Aktualisierung des Agenten** (Entscheid E10 in
  `docs/features/multitenancy.md`). Bis dahin ist ein Update ein erneutes
  Ausrollen des MSI — es ersetzt die Fassung an derselben Stelle und lässt
  Zustand und Konfiguration stehen.
