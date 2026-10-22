# Magister Connector Agent

Läuft **auf dem Domänencontroller** des Kunden und **telefoniert nach Hause**:
die Plattform baut nie eine Verbindung ins Kundennetz auf, und LDAP verlässt
den DC nicht. Am AD meldet er sich per Kerberos als **Maschinenkonto des DC**
an — kein Dienstkonto, kein Passwort, kein Zugriff aus einer tieferen Ebene
auf Tier 0. Referenz: [ADR-0014](../docs/adr/0014-ad-connector-agent.md),
Nachtrag „Agent auf dem DC".

## Was der Agent ist — und was er nicht ist

Er ist ein **Ausführender mit eigenen Grenzen**, kein Fernsteuerungs-Endpunkt.
Die Plattform kann ihm nur die bekannten AD-Operationen auftragen; es gibt
keinen Weg, freies LDAP, PowerShell oder ein Skript zu schicken.

**Eingestellt wird er im Cockpit.** Auf dem DC steht nur der Weg zur
Plattform (Endpunkt, ggf. CA); OU-Freigabe, weitere geschützte Gruppen,
Domänencontroller und Suchbasen holt der Agent über den beglaubigten Kanal
(`GET /connector/config`) und merkt sich die letzte Fassung.

| Grenze | Wo festgelegt | Was sie verhindert |
|---|---|---|
| Methoden-Allowlist | im Agenten fest | alles außer den bekannten Operationen |
| Gesperrte Container | im Agenten fest (und im Cockpit) | ganze Domäne, Domain Controllers, Builtin, System, Configuration … |
| OU-Freigabe | Cockpit, vom Agenten nachgeprüft | Zugriff auf Objekte außerhalb der freigegebenen OUs |
| Geschützte Gruppen | im Agenten fest, Cockpit kann ergänzen | Aufnahme in privilegierte Gruppen (deutsch **und** englisch benannt) |
| Geschützte Konten | im Agenten fest | jede Änderung an Konten mit `adminCount=1` oder `isCriticalSystemObject` |
| Attribut-Denylist | im Agenten fest | `userAccountControl`, `servicePrincipalName`, `memberOf` und Verwandte |

Die Annahme dahinter ist unbequem und beabsichtigt: **die Plattform könnte
kompromittiert sein.** Was im Agenten fest steht, kann sie nicht ändern und
nicht abschalten; eine Freigabe auf die ganze Domäne oder auf Domain
Controllers verwirft der Agent, auch wenn das Cockpit sie schickt. Die
Rechte im AD bekommt das Maschinenkonto per Delegation nur auf den
freigegebenen OUs — privilegierte Konten schützt AdminSDHolder zusätzlich.

## Installation (auf dem DC)

Es gibt nur noch das MSI. Es installiert den Agenten und richtet den Dienst
`MagisterConnector` (LocalSystem) ein.

1. Dem Maschinenkonto des DC (über eine Gruppe) auf den freizugebenden OUs
   „Kennwort zurücksetzen", „Benutzerkonten verwalten" und
   „Gruppenmitgliedschaft ändern" delegieren.
2. `msiexec /i magister-connector-x64.msi`
3. Im Cockpit beim Kunden unter „AD-Connector" ein Einmal-Token ausstellen und
   die OUs freigeben.
4. Auf dem DC, Eingabeaufforderung **als Administrator**:
   ```
   magister-connector enroll --endpoint https://connect.magister.ch:46200 [--ca root.pem]
   magister-connector check
   ```
   `enroll` legt die lokale Konfiguration an, erzeugt den Schlüssel lokal,
   meldet sich an, holt die Einstellungen aus dem Cockpit und startet den
   Dienst. `check` prüft Kanal, Cockpit-Konfiguration und LDAPS mit Kerberos.

Nach der Anmeldung nennt der Agent seinen **SPKI-Fingerprint**. Der muss mit
der Anzeige in der Konsole übereinstimmen. Weicht er ab, hat sich jemand
anders mit dem Token angemeldet — deshalb lebt es nur 24 Stunden und gilt nur
einmal.

Der ganze Ablauf mit Begründungen steht in
[`packaging/windows/INSTALL.txt`](packaging/windows/INSTALL.txt) — die Datei
wird mitinstalliert und ist über das Startmenü erreichbar.

**Das MSI startet den Dienst absichtlich nicht** und fragt nicht nach dem
Einmal-Token: eine MSI-Eigenschaft steht in der Kommandozeile des Installers
und damit im Ereignisprotokoll und in jedem Verteilungswerkzeug. Beides
erledigt `enroll`.

Wie das Paket gebaut wird — Payload unter Windows mit PyInstaller, MSI
drumherum unter Linux mit `wixl` — steht in
[`packaging/windows/README.md`](packaging/windows/README.md). Es ist noch
**unsigniert**; siehe dort.

### Die Rechte unter Windows

Im Zustandsverzeichnis liegt der private Schlüssel des Agenten. Unter Windows
schützt ihn die **ACL** (in den Linux-Tests `0700`), und das ist nicht dasselbe
in anderer Schreibweise:

* `os.stat()` liefert unter Windows erfundene Modus-Bits (Verzeichnisse melden
  `0o777`). Die POSIX-Prüfung schlägt dort **immer** fehl — ohne Anpassung
  wäre der Dienst nie gestartet.
* Der Agent dichtet das Verzeichnis deshalb beim Anlegen selbst ab (`icacls`
  mit SIDs, nicht mit lokalisierten Namen) und prüft bei jedem Start die DACL
  über SDDL. Nicht das Installationsprogramm: ein Sicherheitsmerkmal, das nur
  die MSI setzt, fehlt genau bei der Handinstallation, die dann drei Jahre
  läuft.

## Aktualisieren

```
magister-connector update               # als Administrator auf dem DC
magister-connector update --nur-pruefen # nur nachsehen
```

Holt die neueste Fassung über den beglaubigten Kanal aus dem Paketverzeichnis
der Konsole, nur wenn sie neuer ist, prüft die SHA-256, spielt das MSI still ein
und startet den Dienst. Das Cockpit zeigt beim Agenten „Update bereit“. Der
Agent aktualisiert sich **nie von selbst** — ein von der Plattform auslösbares
Update wäre Code auf Tier 0 aus einer Quelle, der der Agent sonst ausdrücklich
nicht traut (ADR-0014, Nachtrag E7).

## Zertifikatserneuerung

Das Agentenzertifikat gilt 90 Tage. Der Dienst erneuert es **selbständig**, 30
Tage vor Ablauf, über den beglaubigten Kanal — bestehendes Client-Zertifikat
plus API-Key, kein Einmal-Token und kein Mensch beim Kunden. Scheitert es,
wird stündlich erneut versucht; es bleibt ein Monat, in dem jemand eingreifen
kann.

`magister-connector check` nennt die Restlaufzeit. Innerhalb der 30 Tage ist
das kein Befund, sondern der vorgesehene Zustand.

**Ein widerrufener Agent kann sich nicht erneuern.** Der Widerruf ist ein
Datenbank-Flag und wird bei jeder Anfrage geprüft — genau deshalb, und nicht
über eine CRL: eine CRL wäre morgen aktuell, und der Erneuerungs-Endpunkt wäre
bis dahin der Weg, aus einem widerrufenen Agenten einen gültigen zu machen.

Bei jeder Erneuerung entsteht ein **neues Schlüsselpaar**. Dasselbe
wiederzuverwenden wäre einfacher und falsch: ein Schlüssel, der über Jahre auf
einem Kundenserver liegt, wird nie gewechselt.

Damit der Wechsel keine Aussperrung werden kann, gelten in der Plattform für
sieben Tage **beide** Fingerprints. Der Grund ist ein konkreter Fall: die
Plattform schreibt den neuen Fingerprint, die Antwort geht auf dem Rückweg
verloren (abgebrochene Verbindung, Proxy-Zeitüberschreitung, Neustart in genau
diesem Moment), und der Agent klopft weiter mit dem alten Schlüssel an — auf
eine Zeile, die ihn nicht mehr kennt. Er wäre ausgesperrt, und zwar endgültig.
Meldet er sich mit dem neuen Fingerprint, gilt die Erneuerung als bestätigt und
der alte wird verworfen.

Lokal wechselt die Erneuerung zwei Dateien (Zertifikat und Schlüssel). Stirbt
der Prozess dazwischen, passen sie nicht zusammen — der Agent legt deshalb das
alte Paar als `.prev` daneben und stellt es beim Start wieder her, wenn das
aktive Paar nicht zusammengehört.

## Deinstallieren

```bash
magister-connector uninstall            # als Administrator
magister-connector uninstall --alles    # auch Konfiguration und Protokoll
```

In dieser Reihenfolge: Dienst anhalten, bei der Plattform abmelden
(`POST /connector/decommission`, beglaubigt mit Zertifikat und API-Key — der
Agent steht danach in der Konsole als widerrufen), Schlüssel, Zertifikat und
Geheimnisse löschen, Programm entfernen (`msiexec /x` mit dem Produktcode
aus der Programmliste). Abgemeldet wird **vor** dem Löschen, weil der Agent danach nicht
mehr beweisen kann, wer er ist. Ist die Plattform nicht erreichbar, wird
trotzdem gelöscht und der Widerruf in der Konsole verlangt (Exit-Code 2).

Unter Windows steht dafür im Startmenü „Connector-Agent deinstallieren".
Über „Apps & Features" bleiben Anmeldung und Schlüssel zurück.

## Voraussetzungen beim Kunden

* **Ausgehend TCP 46200** zu `connect.magister.ch`. Kein Rückfall auf 443
  (Entscheid E11): eine Rückfallebene würde einen geschlossenen Port
  verstecken, bis es darauf ankommt. `check` sagt, ob es geht.
* Installation **auf einem Domänencontroller** (Windows Server 2012 R2 oder
  neuer, 64 Bit).
* Delegierte Rechte für das **Maschinenkonto des DC** auf den freigegebenen
  OUs — kein Dienstkonto, keine Domänen-Admin-Rechte.
* **LDAPS** auf 636 mit einem Zertifikat auf den DNS-Namen des DC.

## Warum der Agent `magister_api` mitbringt

Die siebzehn LDAP-Operationen sind schon geschrieben und getestet. Sie ein
zweites Mal zu schreiben hiesse, zwei Stände zu pflegen, von denen einer
schlechter getestet ist — und Abweichungen fielen erst beim Kunden auf. Der
Agent benutzt deshalb `magister_api.ad`. Damit dafür kein Web-Framework
mitkommt, ist diese Schicht seit ADR-0014 frei von FastAPI
(`magister_api/ad/threadpool.py` erklärt, wie).

## Entwicklung

```bash
cd agent
uv sync --extra dev
uv run pytest
uv run ruff check && uv run ruff format --check
uv run pyright
```

## Was noch fehlt

* **Windows-Signatur.** Das MSI ist **unsigniert**: Windows zeigt eine
  SmartScreen-Warnung, unter AppLocker oder WDAC lässt es sich nicht
  installieren. Entscheid E18 hat das an ein Ereignis gebunden statt an einen
  Zeitpunkt — beim ersten Kunden mit AppLocker oder ab der dritten
  Windows-Installation. Kosten: 400–700 CHF einmalig für die
  Hardware-Verwahrung, 300–600 CHF jährlich für das Zertifikat.
* **Automatische Updates** (Entscheid E10). Bis dahin ist ein Update ein
  erneutes Ausrollen des MSI.
* **Sync-Seiten als Push.** Der Agent holt heute nur Aufträge ab; der
  wiederkehrende AD-Sync läuft noch über den direkten Weg.
