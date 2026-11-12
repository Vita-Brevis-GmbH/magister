# ADR-0023 · Der erste Faktor der Konsole ist ein Passwort, nicht ein Zertifikat

**Status:** angenommen, 2026-09-15
**Kontext:** [ADR-0020](0020-konsolen-anmeldung.md) (Zertifikat + TOTP),
[ADR-0015 D1](0015-authentisierungs-haertung.md) (Konsolen-Listener),
[ADR-0019](0019-operator-zugriff.md) (Operator-Zugriff im Kundenaudit)

## Problem

ADR-0020 D1 macht den öffentlichen Schlüssel des Client-Zertifikats zur
Identität des Operators. Das ist kryptografisch sauber und im Betrieb teuer:

1. **Kein Zertifikat, keine Konsole.** Wer von einem anderen Arbeitsplatz aus
   nachsehen will — ein zweites Notebook, ein Sprung über die Fernwartung, ein
   Kollege in Vertretung — kommt nicht einmal bis zur Anmeldeseite. Der
   Handshake scheitert, bevor irgendetwas antwortet, und die Fehlermeldung des
   Browsers benennt die Ursache nicht.
2. **Verteilen ist Handarbeit.** Ein Zertifikat je Person und Gerät, als PKCS#12
   in jeden Browser importiert, mit Ablaufdatum und ohne Erinnerung.
3. **Der Betreiber sieht die Zuständigkeit anders.** Die Erreichbarkeit der
   Verwaltungsadresse regeln Netz, Firewall und WAF — dort wird sie ohnehin
   gepflegt. Die Anwendung soll sagen, **wer** anklopft, nicht ob der Weg
   erlaubt ist (Entscheid 2026-09-15).

Was am Problem NICHT beteiligt ist: der zweite Faktor. TOTP bleibt, samt
Sperre, Einmal-Codes und verschlüsseltem Geheimnis (ADR-0020 D2).

## Entscheidung

### D1 · Erster Faktor ist Benutzername und Passwort

Der Operator meldet sich mit seinem UPN und einem Passwort an. Der Hash ist
**argon2id** mit denselben Parametern wie beim lokalen Notkonto der
Datenebene (`t=3, m=64 MiB, p=4`) — dieselbe Mechanik, nicht eine zweite.

Fehlversuche zählen. Nach fünf Versuchen ist der Operator fünfzehn Minuten
gesperrt, mit demselben Zähler-Verfahren wie beim zweiten Faktor, aber einem
**eigenen** Zähler: ein falsches Passwort und ein falscher TOTP-Code sind
verschiedene Ereignisse, und wer sie zusammenzählt, sperrt bei halb so vielen
Fehlern.

Die Antwort auf eine gescheiterte Anmeldung ist immer dieselbe — unbekannter
UPN, falsches Passwort und gesperrt sind für den Vorleger nicht zu
unterscheiden. Der Grund steht im Log des Betreibers.

### D2 · Eine Sitzung entsteht erst nach dem zweiten Faktor

Zwischen Passwort und TOTP liegt ein **Zwischenstand**, keine Sitzung: eine
Zeile in `console_sessions` mit `pending_totp = true` und zehn Minuten Frist.
Sie trägt den Cookie durch den zweiten Schritt und berechtigt zu nichts
anderem — jede geschützte Route weist sie ab, als wäre niemand angemeldet.

Warum überhaupt eine Zeile und kein signierter Token: eine Anmeldung, die
sich widerrufen lässt, braucht etwas, das man löschen kann. Und der
Zwischenstand ist genau der Zustand, in dem ein Angreifer mit gestohlenem
Passwort steckt — er soll in der Datenbank sichtbar sein.

### D3 · Das Client-Zertifikat bleibt möglich, ist aber nicht mehr Pflicht

Der Listener verlangt kein Zertifikat mehr (`verify_if_given` statt
`require_and_verify`). Wer eines vorlegt, muss weiterhin eines aus dem
Operator-Zweig vorlegen — ein ungültiges wird abgewiesen, ein fehlendes ist
in Ordnung.

Damit bleiben von den drei Schichten aus ADR-0015 D1 zwei:

| Schicht | vorher | jetzt |
|---|---|---|
| Der Port liegt auf der Verwaltungsadresse | ja | **ja** — und das ist ab hier die tragende Schicht |
| Client-Zertifikat der Plattform-CA | Pflicht | freiwillig, aber geprüft |
| Marker-Kopf der Anwendung (ADR-0015 D1) | ja | **ja** |

Das ist eine bewusste Abwägung und kein Versehen: die Erreichbarkeit der
Verwaltungsadresse ist Sache des Netzes. Wer diese Entscheidung später
umdrehen will, ändert eine Zeile in `cockpit/deploy/caddy/Caddyfile` — die
Anwendung funktioniert mit und ohne Zertifikat.

### D4 · Die Identität hängt am Operator, nicht mehr am Schlüsselpaar

`console_operators.spki_fingerprint` wird optional. Ein Operator **ohne**
Zertifikat ist der Normalfall; einer **mit** Zertifikat behält seinen
Fingerprint, und wer sich mit Zertifikat anmeldet, wird weiterhin darüber
erkannt (der Weg aus ADR-0020 bleibt vollständig erhalten).

Die Sitzung merkt sich den Fingerprint nur noch, wenn es einen gibt. Eine
Sitzung ohne Zertifikat wird nicht gegen einen Fingerprint gegengeprüft —
sie kann es nicht, und das ist der Preis dieser Entscheidung.

### D5 · Einen Operator anlegen bleibt ein Befehl

`add_operator` bekommt `--set-password`. Das Passwort wird **abgefragt**,
nicht als Argument übergeben: was in der Kommandozeile steht, steht in der
Prozessliste und in der Shell-Historie.

Ein Operator ohne Passwort und ohne Zertifikat kann sich nicht anmelden —
das ist der Zustand direkt nach dem Anlegen, und er ist beabsichtigt.

## Folgen

* Der Zugang zur Konsole hängt ab hier daran, dass die Verwaltungsadresse
  nicht erreichbar ist, wo sie es nicht sein soll. Das ist im Netz zu
  pflegen, nicht in dieser Anwendung.
* Passwörter sind Betreiberpflicht: Länge, Einzigartigkeit, Wechsel bei
  Verdacht. Die Anwendung erzwingt nur eine Mindestlänge von zwölf Zeichen.
* ADR-0020 D1 gilt eingeschränkt weiter: das Zertifikat ist **eine**
  Identität, nicht mehr die einzige. D2 (TOTP), D3 (`actor` abgeleitet) und
  D4 (drei Arten von Aufrufern) bleiben unverändert.
* Ein gestohlenes Passwort allein genügt nicht — es bringt bis zum
  Zwischenstand, nicht weiter.

## Verworfen

**Entra ID (OIDC) für die Konsole.** Fachlich der sauberste Weg: MFA über
Conditional Access, kein zweiter Satz Zugangsdaten, Sperren zentral. Verworfen
für diesen Schritt, weil die Konsole damit von der Erreichbarkeit von Entra
abhängt — gerade dann, wenn man sie am dringendsten braucht (Störung,
Wiederherstellung, Kunde offline). Bleibt als Option; D1 schliesst sie nicht
aus.

**Zertifikat behalten und nur das Verteilen erleichtern.** Löst Punkt 2 des
Problems, nicht Punkt 1: wer kein Zertifikat hat, kommt weiterhin nicht bis
zur Anmeldeseite.
