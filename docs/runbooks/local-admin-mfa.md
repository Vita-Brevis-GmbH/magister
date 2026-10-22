# Runbook · Notzugang und zweiter Faktor

> Das lokale Konto ist der Zugang, wenn Entra ID nicht erreichbar ist. Seit
> [ADR-0015](../adr/0015-authentisierungs-haertung.md) D2 verlangt es einen
> zweiten Faktor (TOTP, RFC 6238).
> Status: **umgesetzt** (Phase 0).

## 1 · Was sich für den Betrieb ändert

Das Passwort allein ergibt **keine** Sitzung mehr. Der Ablauf ist zweistufig:

```
Passwort  ──▶  Kein Faktor eingerichtet?  ──▶  Einrichtung erzwungen  ──▶  Sitzung
              Faktor vorhanden?           ──▶  Einmalcode            ──▶  Sitzung
              MFA-Pflicht ausgesetzt?     ──▶  direkt                ──▶  Sitzung
```

Zwischen den Schritten liegt keine Sitzung, sondern nur ein signierter,
fünf Minuten gültiger Nachweis („Challenge"), dass das Passwort gestimmt hat.
Damit gibt es keinen halb privilegierten Zustand, den jeder andere Endpunkt
gegen prüfen müsste.

## 2 · Erste Anmeldung (Einrichtung)

1. Benutzername und Passwort eingeben.
2. Die Oberfläche zeigt einen QR-Code und das Geheimnis im Klartext (für den
   Fall, dass die Kamera nicht geht). Mit einer Authenticator-App scannen.
3. Den angezeigten sechsstelligen Code eingeben.
4. **Zehn Wiederherstellungscodes** erscheinen — genau einmal. Ausdrucken oder
   in den Passwortmanager. Jeder Code funktioniert einmal und ersetzt den
   Einmalcode, wenn kein Telefon zur Hand ist.
5. Erst nach dem Bestätigen („Codes gesichert, weiter") geht es in die App.

Die Einrichtung lässt sich nicht überspringen. Wer sie abbricht, landet beim
nächsten Anmelden wieder dort.

## 3 · Kleine Fallen, die Zeit kosten

- **Ein Code gilt genau einmal.** Wer sich unmittelbar nach der Einrichtung
  abmeldet und wieder anmeldet, muss auf den nächsten Code warten (bis zu 30
  Sekunden). Das ist der Wiedereinspielschutz, kein Fehler.
- **Fünf falsche Codes sperren das Konto für 15 Minuten** — mit einem eigenen
  Zähler, den ein korrektes Passwort *nicht* zurücksetzt. Sonst könnte, wer das
  Passwort hat, den zweiten Faktor beliebig oft durchprobieren.
- **Serverzeit prüfen.** Akzeptiert wird ±30 Sekunden Abweichung. Läuft die Uhr
  des Servers weiter als das, scheitert jeder Code. `timedatectl status` auf
  der Box, NTP muss laufen.
- Der Wiederherstellungscode wird im selben Feld eingegeben wie der Einmalcode.

## 4 · Zurücksetzen — vier Eingriffe

Nur der letzte schwächt etwas ab, und nur befristet.

| Aktion | Wirkung |
|---|---|
| **TOTP zurücksetzen** | Löscht Geheimnis, Bestätigung und alle Wiederherstellungscodes. Beim nächsten Anmelden greift die Einrichtung. Die MFA-Pflicht bleibt. |
| **Neue Wiederherstellungscodes** | Frischer Satz, Geheimnis unberührt. Für „Codes verbraucht". |
| **Konto deaktivieren** | Der Notzugang ist zu. Das „Löschen", das keine Lücke aufmacht. |
| **MFA-Pflicht befristet aufheben** | Passwort allein genügt wieder — 24 Stunden, dann greift die Pflicht von selbst wieder. Verlangt Grund oder Ticket. |

### Auf dem Server (On-prem, ohne Konsole)

```bash
cd /opt/magister                      # oder wo der Compose-Stack liegt
docker compose exec magister-api python -m magister_api.cli.local_admin_totp \
  --reason "VB-2291 Telefon verloren"

# nur neue Wiederherstellungscodes, Geheimnis bleibt:
docker compose exec magister-api python -m magister_api.cli.local_admin_totp \
  --new-recovery-codes --reason "VB-2291"

# Konto schliessen:
docker compose exec magister-api python -m magister_api.cli.local_admin_totp \
  --disable --reason "Abgang Mitarbeiter"
```

Aus einem Repo-Checkout stattdessen:

```bash
cd apps/api && uv run ../../scripts/magister-cli local-admin totp-reset --reason "…"
```

Das gibt **keine neuen Rechte**: wer Shell-Zugang auf die Box hat, hat ohnehin
Datenbank-Zugang. Es macht den Eingriff auditierbar statt zu einem `UPDATE`
von Hand.

### Gehostet (Konsole)

`Kunde → Notzugang` bietet dieselben vier Eingriffe. API-seitig:

| Aktion | Aufruf |
|---|---|
| Status | `GET /admin/local-admin/mfa` |
| Zurücksetzen | `DELETE /admin/local-admin/mfa` |
| Neue Codes | `POST /admin/local-admin/mfa/recovery-codes` |
| Pflicht aussetzen | `POST /admin/local-admin/mfa/suspend` mit `{"reason": "…"}` |

## 5 · Was ein Reset nicht kann

- **Er zeigt nie ein Geheimnis.** Er löscht nur; das neue Geheimnis entsteht
  bei der Einrichtung durch den, der sich anmeldet. Ein Operator kann sich
  damit keinen funktionierenden zweiten Faktor ausstellen.
- **Das Passwort zurücksetzen ist eine getrennte Handlung** mit eigenem
  Audit-Eintrag. Wer beides tut, verschafft sich Zugang zum Notkonto — das
  liegt in der Natur eines Break-Glass-Kontos, hinterlässt aber zwei Spuren.

## 6 · Audit

Alle Eingriffe stehen in `audit_events` und sind für den Kunden lesbar:

| Ereignis | Wann |
|---|---|
| `local_totp_enrolled` | Einrichtung abgeschlossen (mit Anzahl ausgegebener Codes) |
| `local_totp_reset` | Faktor zurückgesetzt |
| `local_recovery_codes_regenerated` | Neue Codes erzeugt |
| `local_account_disabled` | Konto deaktiviert |
| `local_mfa_requirement_suspended` | Pflicht ausgesetzt, mit Grund und Ablaufzeitpunkt |
| `local_login` | Anmeldung, mit `second_factor` = `totp` / `recovery_code` / `suspended` |

Weder Geheimnis noch Codes landen je in einem Audit-Payload — die
Allowlist in `magister_api/audit/allowlist.py` würde das auch verweigern.

## 7 · Alles verloren (kein Telefon, keine Codes)

Genau dafür sind die vier Eingriffe aus Abschnitt 4 da. Ist auch der Weg
dorthin versperrt — kein Konsolen-Zugang und kein Shell-Zugang — bleibt nur
OIDC. Deshalb: **Wiederherstellungscodes gehören an einen Ort, der unabhängig
von Magister erreichbar ist**, und das Verfahren aus Abschnitt 4 sollte einmal
geübt worden sein, bevor man es braucht.

## 8 · Abschalten (nicht empfohlen)

`MAGISTER_LOCAL_MFA_REQUIRED=0` hebt die Pflicht dauerhaft auf. Das macht den
lokalen Weg wieder zu dem, was ADR-0015 gerade beseitigt hat: ein Anmeldeweg
ohne zweiten Faktor. Wer eine zeitlich begrenzte Ausnahme braucht, nimmt die
24-Stunden-Aussetzung aus Abschnitt 4 — die läuft von selbst ab.
