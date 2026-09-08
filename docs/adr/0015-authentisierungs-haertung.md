# ADR 0015: Authentisierungs-Härtung — Konsolen-Port, TOTP für lokale Konten, AD-Login entfernen

**Status:** Vorschlag · 2026-09-08
**Kontext:** Drei Massnahmen, die die Anmeldewege verkleinern und härten. Sie
sind von der Mandantenfähigkeit unabhängig und können vor
[ADR-0013](0013-mandantenfaehigkeit-control-plane.md) in die bestehenden
Installationen gehen.

## Problem

Heute gibt es drei Anmeldewege: OIDC gegen Entra (MFA über Conditional Access),
ein lokales Notkonto (Benutzername plus Passwort, ohne zweiten Faktor) und den
direkten AD-Login (Benutzername plus Passwort per LDAPS-Bind, ebenfalls ohne
zweiten Faktor). Der schwächste Weg bestimmt das Sicherheitsniveau — die
sorgfältig erzwungene MFA auf dem OIDC-Pfad ist wertlos, solange daneben zwei
Wege ohne zweiten Faktor offen stehen.

Dazu kommt: die Global-Admin-Oberfläche aus ADR-0013 kann Sitzungen in jeden
Kunden ausstellen. Sie soll aus dem Internet gar nicht erreichbar sein.

## Entscheidung

### D1 · Die Konsole bleibt im internen Netz, auf einem eigenen Listener

Zwei Oberflächen mit zwei verschiedenen Erreichbarkeiten:

| | Kundenoberfläche | Konsole |
|---|---|---|
| Erreichbarkeit | öffentlich, aus dem Internet | **nur im internen Netz** |
| Listener | `0.0.0.0:443` | `10.0.0.5:4444` |
| Wer | Lehr- und Leitungspersonen | Global Admin, Global Operator |
| Schutz | MFA über Entra, WAF davor | nicht geroutet, dazu Client-Zertifikat |

**Die Bindung an die interne Adresse ist die Massnahme.** Der Listener wird
ausschliesslich auf der Management-Adresse veröffentlicht, nicht auf `0.0.0.0`:

```yaml
ports:
  - "0.0.0.0:443:443"        # Kundenoberfläche
  - "10.0.0.5:4444:4444"     # Konsole, nur internes Netz
```

Damit ist die Konsole aus dem Internet nicht erreichbar — nicht verborgen,
sondern nicht geroutet. Der eigene Port ist deshalb keine Verschleierung: er ist
die Trennlinie, an der die Bindung überhaupt möglich wird. Die Portnummer selbst
ist beliebig; entscheidend ist, dass dieser Listener nie auf der öffentlichen
Adresse erscheint. Der Kunden-vhost auf 443 routet **nie** zur Konsole.

**Kein Quell-IP-Allowlisting in Magister.** Das erledigen Fortigate und WAF
davor, wo es hingehört — Firewall-Regeln in der Anwendung zu pflegen wäre eine
zweite, schlechter gewartete Wahrheit. Magister kennt nur die
Schnittstellen-Bindung.

**Client-Zertifikat** auf dem Konsolen-Listener bleibt vorgesehen: Caddy verlangt
`client_auth { mode require_and_verify }` gegen dieselbe private CA wie der
Connector (ADR-0014). Ohne Operator-Zertifikat kommt der TLS-Handshake nicht
zustande. Begründung, obwohl der Port intern ist: ein internes Netz ist keine
Vertrauensgrenze — ein übernommener Arbeitsplatz-PC steht darin. Wer diese
Schicht zunächst weglassen will, kann das; dann trägt die Bindung an die interne
Adresse allein, und das sollte eine bewusste Entscheidung sein, keine Lücke.

Dazu ein Riegel in der Anwendung: die Konsole weist jede Anfrage ab, die nicht
über den Management-Listener kam (Marker-Header, den ausschliesslich dieser
Site-Block setzt, oder ein separater Container-Listener). Eine Fehlkonfiguration
im Reverse-Proxy exponiert die Konsole so nicht.

Die Operator-Identität bleibt OIDC mit phishing-resistentem Faktor
(WebAuthn/FIDO2 über Conditional Access, ADR-0013 D2) — das Client-Zertifikat
ist das Netz-Tor, nicht der Benutzer.

### D2 · TOTP für lokale Konten, verpflichtend

Das lokale Notkonto (`local_admins`) bekommt einen zweiten Faktor nach RFC 6238:

- Neue Spalten: `totp_secret_enc` (pgcrypto, wie die übrigen Geheimnisse),
  `totp_confirmed_at`, `totp_last_step`, `recovery_codes` (argon2id-gehasht,
  einmalig verwendbar, zehn Stück).
- SHA-1, 6 Stellen, 30 s, Drift ±1 Schritt. `totp_last_step` verhindert, dass
  ein bereits akzeptierter Zeitschritt ein zweites Mal gilt.
- **Einrichtung erzwungen:** eine lokale Sitzung ohne `totp_confirmed_at`
  erreicht ausschliesslich `/auth/local/totp/enroll` und `/auth/logout`. Kein
  Überspringen, keine Übergangsfrist.
- Anmeldung wird zweistufig: Passwort, dann Einmalcode. Falsche Codes zählen auf
  denselben Zähler wie falsche Passwörter, die bestehende Kontosperre (fünf
  Fehlversuche, `423`) greift damit unverändert.
- QR-Code als **serverseitig gerendertes Inline-SVG** (`segno`, reines Python).
  `img-src 'self' data:` ist in der CSP schon erlaubt — kein CDN, keine
  CSP-Lockerung.
- Wiederherstellungscodes werden einmal angezeigt; ein benutzter Code verfällt.
- `MAGISTER_LOCAL_MFA_REQUIRED` mit Default **true**.

#### Zurücksetzen — vier klar getrennte Eingriffe

Ein verlorenes Telefon darf kein Totalverlust sein. Es gibt vier Aktionen, und
nur eine davon schwächt etwas ab:

| Aktion | Wirkung | Wer |
|---|---|---|
| **TOTP zurücksetzen** | Löscht Geheimnis, Bestätigung und alle Wiederherstellungscodes. Beim nächsten Anmelden landet das Konto zwingend in der Einrichtung. Die MFA-Pflicht bleibt. | Global Admin (gehostet) · CLI auf dem Server (on-prem) |
| **Neue Wiederherstellungscodes** | Erzeugt einen frischen Satz, lässt das Geheimnis unberührt. Für „Codes verbraucht", nicht für „Telefon weg". | dieselben |
| **Konto deaktivieren** | Setzt `enabled=false`. Der Notzugang ist zu; nichts wird geschwächt. Das ist das „Löschen", das keine Lücke aufmacht. | dieselben |
| **MFA-Pflicht befristet aufheben** | Passwort allein genügt wieder — **befristet auf 24 Stunden**, danach greift die Pflicht automatisch wieder. Sichtbarer Warnbalken in der Oberfläche, während sie aufgehoben ist. | Global Admin, mit Grund/Ticket |

Die letzte Aktion ist die ehrliche Antwort auf „den OTP löschen": ohne Frist
wäre sie ein dauerhafter Weg ohne zweiten Faktor und würde D2 aushebeln. Mit
Frist ist sie eine Notfallmassnahme, die sich selbst zurücknimmt.

**Zwei Zugangswege für den Reset, weil es zwei Betriebsarten gibt:**

- **Gehostet:** Konsole → Kunde → Notzugang. Der Reconciler schreibt in das
  Kundenschema; alle vier Aktionen stehen dort.
- **On-prem:** es gibt keine Konsole. Deshalb ein CLI-Unterbefehl auf dem
  Server, neben `hash-password` und `seed-demo`:
  `magister-cli local-admin totp-reset` (dazu `--new-recovery-codes`,
  `--disable`). Wer Shell-Zugang auf die Box hat, hat ohnehin
  Datenbank-Zugang — das Verfahren gibt also keine neuen Rechte, es macht den
  Eingriff nur auditierbar statt zu einem `UPDATE` von Hand.

**Zwei Eigenschaften, die das Verfahren tragen:**

1. **Ein Reset zeigt nie ein Geheimnis.** Er löscht nur; das neue Geheimnis
   entsteht erst bei der Einrichtung durch den Kunden. Ein Operator kann sich
   damit keinen funktionierenden zweiten Faktor ausstellen.
2. **Passwort-Reset ist eine getrennte, getrennt auditierte Handlung.** Ein
   Operator, der beides tut, verschafft sich Zugang zum Notkonto — das liegt in
   der Natur eines Break-Glass-Kontos. Sichtbar bleibt es trotzdem: die
   Ereignisse `local_totp_reset`, `local_recovery_codes_regenerated`,
   `local_account_disabled` und `local_mfa_requirement_suspended` stehen im
   Audit des Kunden und in dessen Liste „Zugriffe von Vita Brevis", nicht nur im
   Plattform-Audit.

**Warum TOTP und nicht WebAuthn an dieser Stelle:** Das lokale Konto ist der
Notzugang, wenn OIDC ausfällt — oft von einer Konsolen- oder KVM-Sitzung aus.
Ein Code aus der Telefon-App funktioniert dort; ein Roaming-Authenticator liegt
womöglich nicht bereit. WebAuthn kann später als zusätzliche Methode dazukommen.

Als Abhängigkeit `pyotp` statt eigener HMAC-Implementierung: bei einem
Sicherheitsprimitiv ist eine geprüfte Umsetzung die richtige Wahl.

### D3 · Der AD-Login wird entfernt, nicht abgeschaltet

Begründung:

- Der Benutzer tippt sein AD-Passwort in Magister; die Anwendung nimmt ein
  Klartext-Passwort eines Verzeichnisbenutzers an und bindet es gegen das AD.
  Genau diesen Pfad vermeiden die Niemals-Regeln sonst überall.
- Kein zweiter Faktor. Der Weg ist damit eine dokumentierte Umgehung der
  Conditional-Access-MFA auf dem OIDC-Pfad.
- Ein öffentlich erreichbarer Endpunkt, über den echte AD-Konten durchprobiert
  und — durch die AD-Kontosperre — reihenweise gesperrt werden können. Das ist
  auch ein Verfügbarkeitsproblem, nicht nur ein Vertraulichkeitsproblem.
- Gehostet müsste der Kunde Benutzerpasswörter an die Plattform schicken. Nicht
  vertretbar.

Ein Schalter genügt nicht: solange der Code steht, kann er wieder eingeschaltet
werden. Er verschwindet.

**Was bleibt:** OIDC gegen Entra als regulärer Weg und das lokale Notkonto mit
TOTP. Zwei Wege, beide mit zweitem Faktor.

**Was ausdrücklich bleibt:** `probe_bind_as_user`. Die drei
Passwort-Reset-Dienste prüfen damit ein *gerade selbst gesetztes* Passwort — kein
benutzergeliefertes Geheimnis, ein anderer Sachverhalt.

**Ausbau in zwei Schritten** (erweitern/verengen, wie bei Migrationen):

*Release N — Code und Oberfläche weg:*

| Datei | Was |
|---|---|
| `routers/auth.py` | `POST /auth/login/ad`, `_AD_REFUSAL_TO_STATUS`, `ad_login_enabled` in `/auth/capabilities` |
| `services/auth.py` | `complete_ad_login`, Audit-Aktionen `ad_login` / `ad_login_failed` |
| `ad/client.py` | `authenticate`, `_sync_authenticate`, `_sync_lookup_login_account` |
| `ad/rpc_client.py` | `authenticate` |
| `ad/rpc.py` | `"authenticate"` aus `ALLOWED_METHODS` |
| `auth/effective_settings.py` | Overlay für `ad_login_enabled` / `ad_login_group` |
| `services/app_settings.py`, `schemas/app_settings.py` | beide Felder in Lesen, Schreiben, Seed und Redaktion |
| `schemas/auth.py` | `AdLoginRequest` |
| `config.py` | `ad_login_enabled`, `ad_login_group` |
| `apps/web/src/routes/login.tsx` | `AdLoginForm`, `showAd`, Fehlerabbildung |
| `apps/web/src/api/hooks.ts`, `types.ts` | `useAdLogin`, `AdLoginRequest`, beide Settings-Felder |
| `apps/web/src/routes/_app.admin.settings.tsx` | Abschnitt „AD-Login" |
| `apps/web/src/i18n/{de,fr,it,en}.json` | `auth.login_ad_*`, `auth.errors.ad_login_disabled`, `settings.*.ad_login_*` — in allen vier Sprachen zugleich, `i18n.test.ts` erzwingt Parität |
| `tests/unit/test_module_contracts.py` | Route-Erwartungen |

Zusätzlich: der Start **bricht laut ab**, wenn `MAGISTER_AD_LOGIN_ENABLED` oder
`MAGISTER_AD_LOGIN_GROUP` gesetzt ist, mit Verweis auf diesen ADR. Eine
entfernte Sicherheitseinstellung darf nicht stillschweigend ignoriert werden.

*Release N+1 — Schema:* Alembic entfernt `app_settings.ad_login_enabled` und
`app_settings.ad_login_group` (Rückbau von Migration `0019_ad_login`).

**Vor dem Ausbau zu klären:** nutzt heute ein Kunde den AD-Login? Dann muss er
zuerst auf OIDC — Release-Notes und Runbook müssen das benennen.

## Konsequenzen

**Positiv**

- Jeder verbleibende Anmeldeweg hat einen zweiten Faktor.
- Kein Endpunkt mehr, der AD-Passwörter annimmt oder AD-Konten sperren lässt.
- Die Konsole ist aus dem Internet nicht geroutet und ohne Operator-Zertifikat
  nicht einmal ansprechbar; das Kunden-Usermanagement bleibt öffentlich und
  MFA-geschützt. Zwei Oberflächen, zwei Erreichbarkeiten.
- Der Verlust eines zweiten Faktors ist ein geführter Vorgang mit vier klar
  getrennten Eingriffen statt eines Handgriffs in die Datenbank.
- Konsole und Connector teilen eine CA und ein Widerrufsverfahren — ein
  Mechanismus, nicht zwei.

**Negativ**

- Der Notzugang wird umständlicher: ohne Telefon oder Wiederherstellungscode
  braucht es einen Reset über die Konsole oder das CLI. Das Verfahren muss
  dokumentiert und geübt sein, sonst ist es der neue Ausfallpunkt.
- Die befristete Aufhebung der MFA-Pflicht ist ein mächtiger Eingriff. Sie muss
  eng auditiert und in der Oberfläche unübersehbar sein, sonst wird sie zur
  Gewohnheit.
- Wer heute den AD-Login nutzt, muss migrieren.
- Operator-Zertifikate müssen auf jedem Gerät ausgerollt und beim Verlust eines
  Geräts widerrufen werden.
- Eine neue Abhängigkeit (`pyotp`) und eine neue Migration.

## Alternativen verworfen

- **AD-Login nur abschalten (Default aus).** Ist er heute schon; der Code bleibt
  aber einschaltbar und muss weiter gepflegt und geprüft werden.
- **AD-Login mit TOTP nachrüsten.** Löst den Klartext-Passwortpfad und das
  Aussperren echter AD-Konten nicht.
- **Konsole nur über VPN, ohne eigenen Port.** Funktioniert, macht aber die
  Firewall-Regel und die Client-Auth-Politik unschärfer und mischt Kunden- und
  Konsolen-Verkehr auf einem vhost.
- **Konsole öffentlich, nur mit MFA geschützt** (wie die Kundenoberfläche). Die
  Konsole kann Sitzungen in jeden Kunden ausstellen; sie gehört nicht ins
  Internet, auch nicht mit MFA.
- **Quell-IP-Allowlisting in Magister.** Doppelte Wahrheit neben Fortigate und
  WAF, und die schlechter gewartete von beiden.
- **MFA-Pflicht dauerhaft aufhebbar machen.** Wäre ein permanenter Weg ohne
  zweiten Faktor und würde D2 aushebeln. Deshalb nur befristet.
- **WebAuthn statt TOTP für lokale Konten.** Am Notzugang oft nicht verfügbar;
  als zusätzliche Methode später sinnvoll.
