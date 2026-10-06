# ADR-0024 · Betrieb aus der Konsole

**Status:** Angenommen · 2026-10-06
**Bezug:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) (Control Plane),
[ADR-0016](0016-sicherung-wiederherstellung-export.md) (Sicherung),
[ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md) (Politik in der Konsole),
[ADR-0014](0014-ad-connector-agent.md) (Connector)

## Problem

Auf dem Dev-Host mit dem ersten gehosteten Kunden zeigten sich sechs Lücken,
die alle dieselbe Ursache haben: die Konsole konnte Dinge **anordnen**, aber
nicht **sehen**, ob sie ankamen — und einige Handlungen, die gehostet der
Plattform gehören, sassen noch im Kundenportal.

1. In der Konsole stand der Kunde auf „Firma", sein Portal zeigte „Schule".
   Ob der Abgleich überhaupt lief, war von der Konsole aus nicht festzustellen.
2. Der AD-Sync meldete „Such-Basis nicht gesetzt — bitte oben eintragen".
   Oben gab es kein Feld: die Einstellungen waren gehostet aus dem Portal
   entfernt (ADR-0017), eine Oberfläche in der Konsole fehlte.
3. Entra ID liess sich gar nicht verbinden: das Client-Secret war ein
   Geheimnis, und ADR-0017 D2 verwies dafür auf ein CLI, das nie gebaut wurde.
4. Sicherungen standen dauerhaft auf „written": niemand prüfte sie, und eine
   Wiederherstellung liess sich nicht erfassen.
5. Neustart und Update sassen im Kundenportal — der Admin **eines** Kunden
   startete den Host **aller** Kunden neu.
6. Dasselbe für „Demodaten entfernen" und „Aktivitäten zurücksetzen".

## Entscheidung

### D1 · Die Datenebene meldet ihren Zustand

Nach jedem Abgleich schickt die Datenebene je Kunde eine **Zustandsmeldung**
an die Konsole (`POST /api/tenants/{id}/status`): ob der Abgleich gelang,
welches Profil und welche Module wirksam sind, wie der AD-Sync steht (Weg,
fehlende Einstellungen, letzter Erfolg, letzter Fehlschlag, Anzahl), welche
Geheimnisse gesetzt sind (nur ob, nie was), der öffentliche Schlüssel zum
Versiegeln (D3) und die Ergebnisse von Wartungsaufträgen (D4).

Auch ein gescheiterter Abruf des Soll-Zustands wird gemeldet. Und meldet
sich eine Installation nie, sagt die Konsole genau das — mit der Logzeile, in
der die Ursache steht.

Die Meldung ist der zweite Rückkanal neben der Schemastand-Meldung
(ADR-0021 D2). Sie trägt keine Personendaten: Zeitpunkte, Zähler,
Schlüsselnamen, Ursachen-Codes. Die Konsole prüft sie streng
(`extra=forbid`, begrenzte Längen).

Dazu: der Soll-Zustand enthält jetzt **immer** `module_overrides`, auch leer.
Ohne diese Aussage blieben bei bestehenden Portalen Schalter stehen, die dort
vor der Konsole gesetzt wurden — der eigentliche Grund für „Firma in der
Konsole, Schule im Portal". Bestehende Portale werden damit beim nächsten
Abgleich korrigiert, ohne Handgriff.

### D2 · Die Einstellungen eines Kunden haben eine Oberfläche

Reiter „Einstellungen" je Kunde: Entra ID (Tenant-Id → Issuer, Client-Id,
Umleitungs-URI aus dem Hostnamen, Scopes), Zugang (erste Admins,
Mail-Domänen), Active Directory (Suchbasen, OUs, Gruppen, Intervall) und
NinjaOne. Leer heisst „Plattform-Vorgabe". Geschrieben wird über die
bestehende Fläche `PUT /api/tenants/{id}/settings` mit ihrer Allowlist.

Im Kundenportal verweist eine Konfigurations-Fehlermeldung des AD-Syncs
gehostet auf Vita Brevis statt auf ein Feld, das es dort nicht gibt.

Und: über den Connector braucht die Datenebene **keinen** Domänencontroller
— den kennt der Agent. Verlangt wurde er trotzdem, und ohne ihn übersprang
der wiederkehrende Abgleich einen gehosteten Kunden still.

### D3 · Geheimnisse werden versiegelt, nicht gespeichert

ADR-0017 D2 sagt: in der Konsole liegen keine Kundengeheimnisse. Dabei
bleibt es — gelesen als „keine, die sie lesen kann".

Die Datenebene leitet je Kunde ein X25519-Schlüsselpaar aus seinem
Geheimnisschlüssel ab (HKDF, nichts zusätzlich zu sichern) und meldet den
öffentlichen Teil (D1). Die Konsole versiegelt ein eingegebenes Geheimnis
damit (versiegelte Box: Ephemeral-X25519, HKDF-SHA256, ChaCha20-Poly1305;
die zusätzlichen Daten binden das Chiffrat an Kunde und Feld) und speichert
**nur das Chiffrat**. Der Klartext lebt nur in der einen Anfrage, wird nicht
protokolliert und nicht zurückgegeben. Die Datenebene öffnet es beim
Abgleich und schreibt es, mit dem Kundenschlüssel verschlüsselt, über den
bestehenden einen Schreibweg ins Kundenschema.

Versiegelbar sind nur `oidc_client_secret` und `ninja_client_secret`
(Allowlist auf beiden Seiten). Das AD-Bind-Passwort bleibt beim Agenten des
Kunden (ADR-0014); der private Webserver-Schlüssel bleibt auf dem
Anwendungsserver.

Was eine übernommene Konsole damit erreicht: sie kann ein Geheimnis
**ersetzen** (das konnte sie über die Einstellungen schon immer indirekt,
etwa durch einen anderen Issuer) und das Geheimnis sehen, das jemand **in
diesem Moment** eintippt. Sie kann keine gespeicherten Geheimnisse lesen.

Wird der Kundenschlüssel gedreht, ändert sich das Schlüsselpaar; die Konsole
erkennt das am Fingerabdruck und zeigt das Geheimnis als neu zu setzen.

### D4 · Wartung als Auftrag, nicht als Endpunkt im Portal

„Demodaten entfernen" und „Aktivitäten zurücksetzen" sind gehostet
Wartungsaufträge in der Konsole: mit Grund (steht im Protokoll des Kunden)
und Bestätigung durch Eintippen des Kürzels. Die Datenebene holt sie mit dem
Soll-Zustand ab und führt jeden **genau einmal** aus — gesichert durch ein
Advisory-Lock auf die Auftrags-Id und ein Audit-Ereignis
`platform_maintenance_executed` mit der Auftrags-Id als Ziel, das auch das
Zurücksetzen des Protokolls überlebt. Das Ergebnis geht mit der nächsten
Zustandsmeldung zurück.

Gehostet werden `/admin/demo-data/purge` und `/admin/audit/reset` nicht
gemountet. On-prem bleibt alles wie bisher.

### D5 · Neustart und Update gehören der Plattform

Gehostet werden `/admin/system/*` nicht gemountet; die Konsole hat eine
Seite „Plattform" mit Neustart und Update. Dasselbe Sicherheitsmodell wie
vorher: die API legt nur eine Auftragsdatei ab, ein Host-Agent
(`scripts/plattform-ops-agent.sh`, systemd-Timer, eingerichtet mit
`plattform-aufbau.sh ops-agent`) kennt genau zwei Aufträge und führt sie aus.

### D6 · Sicherungen werden geplant, geprüft und sind wiederherstellbar

* **Täglich**: ein Zeitplaner in der Konsole sichert jeden aktiven Kunden
  einmal am Tag (`COCKPIT_BACKUP_DAILY_AT`, UTC). „Einmal" wird an der
  Datenbank entschieden, nicht im Speicher — ein Neustart zieht keine zweite.
* **Prüfen und Wiederherstellen** bleiben auf dem Backup-Host (ADR-0016 D2).
  Neu ist ein Prüfer (`cockpit_api.cli.backup_worker`), der sich seine
  Arbeit bei der Konsole holt, die bestehenden Werkzeuge ausführt und die
  Ergebnisse meldet. Sein Abruf ist zugleich sein Lebenszeichen, die
  Oberfläche zeigt es. Auf einem Einzelhost startet ihn ein systemd-Timer in
  einem **eigenen**, kurzlebigen Container, in den nur der private Schlüssel
  eingehängt wird (`plattform-aufbau.sh backup-pruefer`).
* **Wiederherstellung** lässt sich in der Oberfläche erfassen, durch eine
  zweite Person freigeben und als umgeschaltet vermerken (ADR-0016 D5).

### D7 · Der Connector lässt sich prüfen

Der Reiter „AD-Connector" hat einen Verbindungstest: ein echter Auftrag
`probe_service_connection_detailed` über Warteschlange, Agent und LDAPS ins
AD. Verfällt er, holt der Agent nicht ab; sonst steht das Ergebnis da
(Bind gelungen, DC nicht erreichbar, Dienstkonto abgewiesen …). Daneben steht
der AD-Sync-Zustand aus der Zustandsmeldung.

## Konsequenzen

* Die Konsole sieht, was ankommt. „Hier eingestellt, dort nicht angekommen"
  ist eine Zeile in der Übersicht und keine Fehlersuche in Logs.
* Ein Kunde lässt sich vollständig aus der Konsole einrichten, Entra ID
  eingeschlossen. Der Handgriff auf dem Anwendungsserver aus ADR-0017 D2
  entfällt für die zwei versiegelbaren Geheimnisse.
* Zwei neue Host-Helfer (Ops-Agent, Prüfer) laufen als root-Timer. Beide
  führen nur Festgelegtes aus; was sie tun, steht im Skript, nicht im Auftrag.
* Die Konsolen-Datenbank hat vier neue Tabellen (Migration 0017). Keine
  davon enthält Personendaten oder lesbare Geheimnisse.

## Alternativen verworfen

* **Geheimnisse im Klartext in der Konsole.** Einfacher und genau der Ort,
  an dem die Geheimnisse aller Kunden zusammenkämen (ADR-0017 D2).
* **Geheimnisse über das CLI auf dem Anwendungsserver.** Der Weg aus
  ADR-0017 D2; er wurde nie gebaut, und er verlangt für jeden Kunden eine
  Shell auf dem Anwendungsserver. Die versiegelte Box erfüllt dieselbe
  Zusage ohne diesen Handgriff.
* **Die Konsole schreibt direkt ins Kundenschema.** Bricht ADR-0017 D3 (die
  Datenebene zieht, die Konsole hat keinen Datenbankzugang zum Kunden).
* **Prüfen in der Konsole.** Hiesse, den privaten Backup-Schlüssel neben die
  Anwendung zu legen (ADR-0016 D2).
