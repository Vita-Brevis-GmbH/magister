# Mockup · Global-Admin-Konsole (Mandantenfähigkeit)

Entwurf der Oberfläche zu [ADR-0013](../../adr/0013-mandantenfaehigkeit-control-plane.md)
und [docs/features/multitenancy.md](../../features/multitenancy.md).
**Entwurf, keine Implementierung.**

## Bildschirme

| Datei | Inhalt |
|---|---|
| `Login.dc.html` | Anmeldung an der Konsole (eigene Origin, Entra ID mit Hardware-Schlüssel) |
| `Kundenwahl.dc.html` | Kundenwahl nach der Anmeldung, mit Grund/Ticket |
| `Main.dc.html` | Kundenliste — Startseite der Konsole |
| `KundeDetail.dc.html` | Ein Kunde: Systemeinstellungen (OIDC, AD, Konnektoren) |
| `NeuerKunde.dc.html` | Kunde erfassen, inklusive Wahl der Datenbank-Trennung |
| `Rechte.dc.html` | Globale Rollen- und Rechte-Matrix |
| `Vorlagen.dc.html` | Globale Vorlagen und Rollout auf Kunden |
| `Isolation.dc.html` | Datenbank-Trennung und Migrations-Wellen |
| `Sicherungen.dc.html` | Sicherung pro Kunde, Prüf-Wiederherstellung, Restore und Export |
| `Kundenkontext.dc.html` | Hinweisbalken im Kunden-System — Operator- und Kundensicht |
| `Connector.dc.html` | Kunde → AD-Connector: Agent-Status, Anmeldedaten, erlaubte Operationen |
| `AgentSetup.dc.html` | Agent-Paket beziehen — Einmal-Token, Prüfsumme, Firewall-Anforderung |
| `Zugangswege.dc.html` | Anmeldewege nach der Härtung, inklusive Listener-Matrix |
| `MfaSetup.dc.html` | TOTP-Einrichtung für ein lokales Konto (Kunden-UI) |
| `Notzugang.dc.html` | Kunde → Notzugang: die vier OTP-Eingriffe, plus der CLI-Weg für On-prem |

`canvas.json` legt die Anordnung auf drei Seiten fest (Konsole · Global anwenden und Betrieb · Zugang und Connector).

## Gestaltung

Farben, Schrift, Abstände, Radien und Bausteine sind aus `apps/web` übernommen
(`tailwind.config.ts` + `src/index.css` + `src/components/ui/`): Fraunces als
Überschriftenschrift, Slate-Palette, 8px Kartenradius, 40px Bedienelemente,
48px Tabellenköpfe, `StatusPill`-Abzeichen. Die Konsole setzt sich durch eine
dunkle Kopfzeile (`#0f172a`, der bestehende `primary`-Token) von der
Kundenoberfläche ab.

Alle Kundennamen, Zahlen, Tickets, Zeitstempel, Fingerprints und Tokens sind Platzhalter.

## Bearbeiten

`build.sh` erzeugt die `*.dc.html`-Dateien aus einem gemeinsamen Token-Block —
dort ändern und neu erzeugen:

```bash
./build.sh
```

`_tokens.txt` listet die verwendeten Werte samt Herkunft.
