# Debian-Paket des Connector-Agenten

Ergebnis: `magister-connector_<version>_<arch>.deb` für Debian und Ubuntu.

```bash
agent/packaging/debian/build-deb.sh          # baut nach packaging/debian/
sudo dpkg -i magister-connector_0.1.0_amd64.deb
```

Anders als beim MSI lässt sich hier **alles** auf dem Entwicklerrechner
prüfen — bauen, installieren, aufrufen, entfernen. Das tut auch CI
(`agent-ci.yml`, Job `deb`), und zwar bis zum Purge: ein Paket, von dem nur
der Inhalt geprüft ist, lässt ein kaputtes `postinst` durch.

## Was hineinkommt

| Pfad | Inhalt |
|---|---|
| `/opt/magister-connector/` | venv mit dem Agenten und seinen Abhängigkeiten |
| `/usr/bin/magister-connector` | Aufruf-Hülle mit der Vorgabe `--config /etc/magister-connector/config.json` |
| `/lib/systemd/system/magister-connector.service` | die Unit |
| `/etc/magister-connector/config.example.json` | Konfigurationsvorlage |
| `/etc/magister-connector/ad.env.example` | Vorlage für die AD-Zugangsdaten |

Vom `postinst` angelegt, **nicht** im Paket:

| Pfad | Rechte | Warum nicht im Paket |
|---|---|---|
| `/var/lib/magister-connector/` | `0700`, Dienstkonto | Läge es im Paket, trüge es die Rechte des Bauorts. Hier liegt der private Schlüssel. |
| `/etc/magister-connector/ad.env` | `0640`, `root:magister-connector` | Darin steht das AD-Bind-Passwort. Aus der Vorlage kopiert, damit der Betreiber nur ausfüllen muss. |

## Warum ein venv unter `/opt` und keine `python3-*`-Abhängigkeiten

Der Agent braucht `magister_api` (nicht in Debian), plus `httpx` und
`cryptography` in Fassungen, die nicht auf jedem unterstützten Stand liegen.
Unter Windows liefern wir aus demselben Grund ein eingefrorenes Bündel.

**Der Preis, ausgeschrieben:** das Paket ist 39 MB statt 200 KB, und eine
Sicherheitsaktualisierung an `cryptography` kommt über ein neues Paket von uns
und nicht über `apt upgrade`. Das ist bewusst so entschieden und gehört in den
Betrieb — dieselbe Abwägung wie beim MSI. Wer das nicht will, installiert das
Python-Paket von Hand gegen die Distributions-Bibliotheken; dann liegt die
Versionspflege bei ihm.

Gebaut wird ausdrücklich mit **python3.12**, weil der Agent es verlangt. Das
Skript sucht es, wenn das Vorgabe-Python älter ist.

## Was das Paket absichtlich nicht tut

* **Den Dienst starten.** Zum Installationszeitpunkt ist der Agent nicht
  angemeldet — kein Zertifikat, kein API-Key. Ein Start würde nur eine
  Fehlermeldung ins Journal schreiben. Das `postinst` sagt stattdessen, welche
  drei Befehle folgen.
* **Eine `config.json` schreiben.** Nur die Vorlage. Damit überschreibt ein
  Update nie eine funktionierende Konfiguration — der häufigste Paketfehler
  überhaupt. Die Vorlagen stehen in `conffiles`, die echte `config.json`
  gehört nicht zum Paket und wird deshalb nie angefasst.
* **Beim Purge das Zustandsverzeichnis mitnehmen.** Darin liegen der private
  Schlüssel, die Anmeldung und das Protokoll. Ein Purge, der das löscht, macht
  eine Neuinstallation zu einer Neuanmeldung und entfernt im Zweifel das
  Protokoll, in dem steht, warum jemand deinstalliert hat. Das `postrm` sagt,
  wo es liegt und wie man es entfernt — und dass der Agent dann in der Konsole
  zu widerrufen ist.

## Zwei Fallen, die beim Bauen aufgefallen sind

**Die Shebangs im venv.** `pip install` schreibt in jedes Konsolenskript den
Pfad des Python, mit dem gebaut wurde — also den des Bauverzeichnisses. Ohne
die Umschreibung auf `/opt/magister-connector/bin/python3` startet nach der
Installation nichts, und die Meldung lautet `bad interpreter: No such file or
directory`, was in die falsche Richtung zeigt.

**`dpkg-deb --contents | grep -q`.** `grep -q` bricht beim ersten Treffer ab,
`dpkg-deb` bekommt SIGPIPE und meldet `tar subprocess was killed by signal
(Broken pipe)`. Die folgenden Prüfungen sehen dann eine abgeschnittene Liste
und melden Dateien als fehlend, die drin sind. Das Skript liest den Inhalt
deshalb einmal in eine Datei und sucht darin.

Und ein Fund ausserhalb des Pakets: `apps/api` liess sich **überhaupt nicht**
als Rad bauen. Eine `force-include` in `pyproject.toml` fügte die
Brief-Vorlagen ein zweites Mal hinzu, was hatchling mit `A second file is
being added to the wheel archive at the same path` abweist. Über den
Entwicklungsweg (`uv sync`, editable) fällt das nicht auf, weil dabei kein Rad
entsteht — das Paket war also nie installierbar, ohne dass es jemand merkte.
Aufgefallen ist es hier, weil das `.deb` `pip install apps/api` braucht.

## Noch offen

* **Signatur.** Das Paket ist unsigniert. Für ein `apt`-Repository braucht es
  einen GPG-Schlüssel und `reprepro` oder `aptly` — dieselbe Verwahrungsfrage
  wie beim Code-Signing-Zertifikat für das MSI.
* **Ein Repository.** Heute wird das `.deb` als Datei ausgeliefert; ein
  `apt`-Repository würde `apt upgrade` und damit automatische Aktualisierung
  ermöglichen (Entscheid E10).
* **`lintian`** läuft nicht mit. Das Paket ist kein Debian-Beitrag, und die
  Regeln für `/opt` und ein mitgeliefertes venv würden reihenweise Warnungen
  erzeugen, die alle beabsichtigt sind. Die Prüfungen, die für uns zählen,
  stehen im Bauskript und im CI-Job.
