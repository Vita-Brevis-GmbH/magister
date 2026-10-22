# Mailversand und Erinnerung vor dem Passwort-Ablauf

Windows und Microsoft 365 melden einen nahen Passwort-Ablauf kaum noch.
Magister liest das Ablaufdatum aus dem AD
(`msDS-UserPasswordExpiryTimeComputed`, berücksichtigt Domänen-Richtlinie
und Fine-Grained Password Policies) und schreibt an den eingestellten
Schwellen (Vorgabe 14, 7 und 1 Tag vorher) eine Mail an alle aktiven Konten
mit Mailadresse. Konten ohne Mailadresse stehen in Magister unter
**Benutzer → Passwort-Ablauf → Ohne Mailadresse**, an Schulen zusätzlich in
der Klasse (Spalte „Passwort").

Gesendet wird tagsüber (07–19 Uhr Schweizer Zeit), stündlich geprüft, je
Schwelle genau einmal. Setzt jemand ein neues Passwort, beginnt es für den
neuen Ablauf von vorn. Gescheiterte Mails werden nach einer Stunde
wiederholt.

## 1 · Microsoft 365 (empfohlen)

Microsoft schaltet SMTP mit Benutzername und Passwort ab; Graph bleibt.

1. Entra → App-Registrierungen → Neu: z. B. „Magister Mailversand".
2. API-Berechtigungen → Microsoft Graph → **Anwendungsberechtigung**
   `Mail.Send` → Administratorzustimmung erteilen.
3. **Auf das Absender-Postfach beschränken** — sonst darf die App als jede
   Person senden. Exchange Online PowerShell:

   ```powershell
   New-ApplicationAccessPolicy -AppId <Anwendungs-Id> `
     -PolicyScopeGroupId noreply@vitabrevis.ch -AccessRight RestrictAccess `
     -Description "Magister: nur Absender-Postfach"
   ```

   (oder RBAC for Applications mit einem Management Scope auf das Postfach).
4. Zertifikate & Geheimnisse → neues Client-Secret. Ablaufdatum notieren.
5. Eintragen:
   * **Plattform-Standard:** Cockpit → Plattform → Mailversand: „Microsoft
     365 (Graph)", Absenderadresse, Mandanten-Id, Anwendungs-Id speichern,
     dann das Client-Secret **versiegeln**.
   * **Eigene Anbindung eines Kunden:** Cockpit → Kunde → Einstellungen →
     Mailversand, dort das Secret beim Kunden versiegeln.
   * **Einzelinstallation:** Einstellungen → System → Mailversand.

## 2 · SMTP

STARTTLS (587) oder TLS (465) — unverschlüsselt gibt es nicht. Ohne
Benutzername wird ohne Anmeldung gesendet (z. B. ein M365-Connector, der
die IP der Plattform zulässt).

## 3 · Prüfen

* Magister → Einstellungen → System → **Testmail senden**. Die Meldung nennt
  bei einem Fehler den Grund (z. B. `graph: sendMail 403 ErrorAccessDenied`
  = Zugriffsrichtlinie oder fehlende Zustimmung).
* Benutzer → Passwort-Ablauf: Spalte „Erinnerung" zeigt, was gesendet wurde.
* Der Text samt Anleitung, wie das Passwort geändert wird, ist die Vorlage
  **Erinnerung Passwort-Ablauf (Mail)** (Vorlagen; gehostet auch als
  Plattformvorlage im Cockpit).

## 4 · Voraussetzungen

* AD-Abgleich über den Connector: der Agent muss eine aktuelle Version haben
  (ältere Agenten liefern das Ablaufdatum nicht; die Übersicht sagt dann
  „Noch keine Ablaufdaten").
* Gehostet: `MAGISTER_PLATFORM_SECRETS_KEY` in `deploy/compose/.env`
  (legt `plattform-aufbau.sh update` an). Gehört in die Sicherung —
  wechselt er, ist das Plattform-Geheimnis neu zu versiegeln.
