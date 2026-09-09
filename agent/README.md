# Magister Connector Agent

Läuft im Netz des Kunden und **telefoniert nach Hause**: die Plattform baut nie
eine Verbindung ins Kundennetz auf, und LDAP verlässt das Kundennetz nicht.
Referenz: [ADR-0014](../docs/adr/0014-ad-connector-agent.md).

## Was der Agent ist — und was er nicht ist

Er ist ein **Ausführender mit eigenen Grenzen**, kein Fernsteuerungs-Endpunkt.
Die Plattform kann ihm nur die siebzehn bekannten AD-Operationen auftragen; es
gibt keinen Weg, freies LDAP, PowerShell oder ein Skript zu schicken. Und was
der Agent tatsächlich tut, begrenzt seine **lokale** Konfiguration:

| Grenze | Wo konfiguriert | Was sie verhindert |
|---|---|---|
| Methoden-Allowlist | im Agenten fest | alles außer den bekannten Operationen |
| OU-Allowlist | `config.json` beim Kunden | Zugriff auf Objekte außerhalb der Magister-OUs |
| Gruppen-Denylist | `config.json`, mit Vorgabe | Aufnahme in privilegierte Gruppen (deutsch **und** englisch benannt) |
| Attribut-Denylist | im Agenten fest | `userAccountControl`, `servicePrincipalName`, `memberOf` und Verwandte |

Die Annahme dahinter ist unbequem und beabsichtigt: **die Plattform könnte
kompromittiert sein.** Der Agent hat ein Dienstkonto, das Passwörter setzen
darf — wer die Plattform übernimmt, würde genau das ausnutzen. Diese Grenzen
liegen deshalb beim Kunden, und die Plattform kann sie nicht ändern, nicht
lesen und nicht abschalten.

## Installation (Linux)

```bash
# 1. Paket auslegen, Dienstkonto anlegen
sudo useradd --system --home /var/lib/magister-connector --shell /usr/sbin/nologin magister-connector
sudo install -d -o magister-connector -g magister-connector -m 0700 /var/lib/magister-connector
sudo install -d -m 0755 /etc/magister-connector

# 2. Konfiguration ablegen und anpassen
sudo install -m 0640 -g magister-connector deploy/config.example.json /etc/magister-connector/config.json
sudo install -m 0600 -o magister-connector deploy/ad.env.example /etc/magister-connector/ad.env
# CA-Bundle der Plattform dazu (kommt mit dem Paket):
sudo install -m 0644 platform-ca.pem /etc/magister-connector/platform-ca.pem

# 3. Anmelden — das Einmal-Token kommt über stdin, damit es nicht in der
#    Prozessliste und nicht in der Shell-History landet.
sudo -u magister-connector magister-connector --config /etc/magister-connector/config.json enroll

# 4. Prüfen, dann Dienst starten
sudo -u magister-connector magister-connector --config /etc/magister-connector/config.json check
sudo install -m 0644 deploy/magister-connector.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now magister-connector
```

Nach der Anmeldung nennt der Agent seinen **SPKI-Fingerprint**. Der muss mit
der Anzeige in der Konsole übereinstimmen. Weicht er ab, hat sich jemand
anders mit dem Token angemeldet — deshalb lebt es nur 24 Stunden und gilt nur
einmal.

## Installation (Windows)

Für Windows gibt es ein MSI. Es installiert den Agenten, richtet den Dienst
`MagisterConnector` ein und legt eine Konfigurationsvorlage ab.

```
msiexec /i magister-connector-0.1.0-x64.msi /qn
```

Danach am Server:

1. `%ProgramData%\Magister Connector\config.example.json` nach `config.json`
   kopieren und anpassen (`endpoint`, `allowed_ous`).
2. Die `MAGISTER_AD_*`-Werte in die Umgebung des Dienstes eintragen.
3. Eingabeaufforderung **als Administrator** (das Startmenü liefert eine):
   `magister-connector enroll`, dann `magister-connector check`.
4. `sc start MagisterConnector`.

Der ganze Ablauf mit Begründungen steht in
[`packaging/windows/INSTALL.txt`](packaging/windows/INSTALL.txt) — die Datei
wird mitinstalliert und ist über das Startmenü erreichbar.

**Das MSI startet den Dienst absichtlich nicht.** Zum Installationszeitpunkt
ist der Agent nicht angemeldet; ein Start würde nur eine Fehlermeldung
erzeugen. Und es fragt nicht nach dem Einmal-Token: eine MSI-Eigenschaft steht
in der Kommandozeile des Installers und damit im Ereignisprotokoll und in
jedem Verteilungswerkzeug.

Wie das Paket gebaut wird — Payload unter Windows mit PyInstaller, MSI
drumherum unter Linux mit `wixl` — steht in
[`packaging/windows/README.md`](packaging/windows/README.md). Es ist noch
**unsigniert**; siehe dort.

### Die Rechte unter Windows

Im Zustandsverzeichnis liegt der private Schlüssel des Agenten. Unter Linux
schützt ihn `0700`; unter Windows schützt ihn die **ACL**, und das ist nicht
dasselbe in anderer Schreibweise:

* `os.stat()` liefert unter Windows erfundene Modus-Bits (Verzeichnisse melden
  `0o777`). Die POSIX-Prüfung schlägt dort **immer** fehl — ohne Anpassung
  wäre der Dienst nie gestartet.
* Der Agent dichtet das Verzeichnis deshalb beim Anlegen selbst ab (`icacls`
  mit SIDs, nicht mit lokalisierten Namen) und prüft bei jedem Start die DACL
  über SDDL. Nicht das Installationsprogramm: ein Sicherheitsmerkmal, das nur
  die MSI setzt, fehlt genau bei der Handinstallation, die dann drei Jahre
  läuft.

## Voraussetzungen beim Kunden

* **Ausgehend TCP 46200** zu `connect.magister.ch`. Kein Rückfall auf 443
  (Entscheid E11): eine Rückfallebene würde einen geschlossenen Port
  verstecken, bis es darauf ankommt. `check` sagt, ob es geht.
* Ein **AD-Dienstkonto** mit delegierten Rechten auf den Magister-OUs — nicht
  Domänen-Admin. Details in
  [kunden-onboarding.md](../docs/runbooks/kunden-onboarding.md) §1.3.
* **LDAPS** auf 636 mit vertrauenswürdigem Zertifikat.

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

* **`.deb` für Debian/Ubuntu.** Das MSI für Windows gibt es
  (`packaging/windows/`), ebenso das Python-Paket, die systemd-Unit und das
  OCI-Abbild. Für Debian fehlt das Paket drumherum.
* **Signatur für das MSI.** Es ist unsigniert; Windows zeigt eine
  SmartScreen-Warnung, und unter AppLocker oder WDAC lässt es sich nicht
  installieren. Braucht ein Code-Signing-Zertifikat auf einem HSM — eine
  Beschaffung mit Kosten und mit derselben Verwahrungsfrage wie beim
  Plattform-CA-Schlüssel.
* **Automatische Zertifikatserneuerung.** Das Zertifikat läuft nach 90 Tagen
  ab; die Erneuerung ist heute ein erneutes `enroll` nach Widerruf.
* **Automatische Updates** (Entscheid E10).
* **Sync-Seiten als Push.** Der Agent holt heute nur Aufträge ab; der
  wiederkehrende AD-Sync läuft noch über den direkten Weg.
