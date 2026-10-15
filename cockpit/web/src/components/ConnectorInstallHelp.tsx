import { useState, type ReactNode } from "react";

type Lang = "de" | "en";

/** Knopf neben der Überschrift „Agenten“ — die Anleitung lesen, bevor ein Token läuft. */
export function ConnectorHelpButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="rounded border px-2 py-0.5 text-xs font-normal text-slate-700 hover:bg-slate-50"
    >
      {open ? "Anleitung schliessen / Close guide" : "? Installationsanleitung / Install guide"}
    </button>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="my-1 select-all overflow-x-auto whitespace-pre-wrap break-all rounded bg-slate-900 px-2 py-1 font-mono text-xs text-slate-100">
      {children}
    </pre>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs text-slate-800">{children}</span>;
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="space-y-1">
      <div className="font-medium">
        {n}. {title}
      </div>
      <div className="space-y-1 text-slate-700">{children}</div>
    </li>
  );
}

export type ConnectorInstallValues = {
  /** `https://connect.…:46200`; leer, wenn die Konsole ihn nicht kennt. */
  endpoint: string;
  /** true: eigene Plattform-CA (root.pem nötig), false: öffentlich vertraut, null: unbekannt. */
  hasCa: boolean | null;
  /** Dateiname des aktuellen MSI, falls im Paketverzeichnis. */
  msiName: string | null;
};

function hostOf(endpoint: string): string {
  try {
    return new URL(endpoint).hostname || "<connector-name>";
  } catch {
    return "<connector-name>";
  }
}

/**
 * Die ganze Einrichtung des AD-Connectors auf dem Domänencontroller — so,
 * dass sie auch jemand ohne Vorwissen beim Kunden durchführen kann.
 *
 * Inhaltlich dieselbe Reihenfolge wie `agent/packaging/windows/INSTALL.txt`
 * (die mitinstalliert wird), hier mit den Werten dieser Plattform eingesetzt
 * und um die Schritte davor ergänzt: Netz prüfen, Dateien holen, Prüfsumme.
 * Englisch für Kunden-IT mit englischem Windows — die Menünamen heissen dort
 * anders.
 */
export function ConnectorInstallHelp(values: ConnectorInstallValues) {
  const [lang, setLang] = useState<Lang>("de");
  return (
    <div className="mb-4 rounded border border-sky-200 bg-sky-50 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2">
        {(["de", "en"] as const).map((l) => (
          <button
            key={l}
            type="button"
            onClick={() => setLang(l)}
            aria-pressed={lang === l}
            className={
              "rounded px-2 py-0.5 text-xs " +
              (lang === l ? "bg-sky-700 text-white" : "border bg-white text-slate-700")
            }
          >
            {l === "de" ? "Deutsch" : "English"}
          </button>
        ))}
      </div>
      <Guide lang={lang} {...values} />
      <Troubleshooting lang={lang} />
    </div>
  );
}

function Guide({ lang, endpoint, hasCa, msiName }: ConnectorInstallValues & { lang: Lang }) {
  const de = lang === "de";
  const ep = endpoint || "https://<connector-name>:46200";
  const host = hostOf(ep);
  const msi = msiName ?? "magister-connector-<version>-x64.msi";
  const caArg = hasCa === false ? "" : " --ca C:\\Temp\\root.pem";
  const enrollCmd = `magister-connector enroll --endpoint ${ep}${caArg}`;

  return (
    <ol className="mb-4 space-y-3">
      <Step n={1} title={de ? "Voraussetzungen klären" : "Check prerequisites"}>
        <ul className="list-disc pl-5">
          <li>
            {de
              ? "Installiert wird auf einem Domänencontroller (Windows Server 2012 R2 oder neuer, 64 Bit) — nicht auf einem Mitgliedsserver. Der Agent meldet sich als Maschinenkonto dieses DC am AD an."
              : "Install on a domain controller (Windows Server 2012 R2 or later, 64-bit) — not on a member server. The agent authenticates to AD as this DC's machine account."}
          </li>
          <li>
            {de
              ? "Ein Konto mit Domänen-Admin-Rechten für die Einrichtung (nur für die Einrichtung; der Dienst braucht keines)."
              : "An account with Domain Admin rights for the setup (setup only; the service needs none)."}
          </li>
          <li>
            {de ? "Ausgehend TCP 46200 vom DC zu " : "Outbound TCP 46200 from the DC to "}
            <Mono>{host}</Mono>
            {de
              ? " — durch Firewall und Proxy, ohne TLS-Aufbrechen. Eingehend braucht es nichts."
              : " — through firewall and proxy, without TLS inspection. Nothing inbound."}
          </li>
          <li>
            {de
              ? "LDAPS auf Port 636 am DC mit einem Zertifikat auf seinen DNS-Namen (Prüfung: ldp.exe, Verbinden mit SSL auf Port 636)."
              : "LDAPS on port 636 on the DC with a certificate for its DNS name (check: ldp.exe, connect with SSL on port 636)."}
          </li>
        </ul>
      </Step>

      <Step n={2} title={de ? "Im Cockpit vorbereiten (Vita Brevis)" : "Prepare in the cockpit (Vita Brevis)"}>
        <p>
          {de
            ? "Unten unter „Freigabe im AD“ die OUs eintragen, in denen der Agent arbeiten darf (Schüler, Lehrpersonen, Klassengruppen). Domänencontroller (volle DNS-Namen) und Suchbasen unter Einstellungen → Active Directory. Ohne freigegebene OU lehnt der Agent alle Verzeichnisaufträge ab."
            : "Below under “Freigabe im AD” enter the OUs the agent may work in (students, teachers, class groups). Domain controllers (full DNS names) and search bases under Einstellungen → Active Directory. Without an allowed OU the agent rejects all directory jobs."}
        </p>
      </Step>

      <Step n={3} title={de ? "Rechte im AD delegieren" : "Delegate rights in AD"}>
        <p>
          {de
            ? "PowerShell als Administrator auf dem DC — Gruppe anlegen und das Computerkonto dieses DC aufnehmen:"
            : "PowerShell as administrator on the DC — create a group and add this DC's computer account:"}
        </p>
        <Code>
          {`New-ADGroup -Name "Magister-Connector" -GroupScope Global -GroupCategory Security\n` +
            `Add-ADGroupMember -Identity "Magister-Connector" -Members (Get-ADComputer $env:COMPUTERNAME)`}
        </Code>
        <p>
          {de
            ? "Dann in „Active Directory-Benutzer und -Computer“ auf jeder freigegebenen OU: Rechtsklick → „Objektverwaltung zuweisen…“ → Gruppe „Magister-Connector“ → diese drei Aufgaben:"
            : "Then in “Active Directory Users and Computers” on every allowed OU: right-click → “Delegate Control…” → group “Magister-Connector” → these three tasks:"}
        </p>
        <ul className="list-disc pl-5">
          {de ? (
            <>
              <li>Setzt Benutzerkennwörter zurück und erzwingt Kennwortänderung bei der nächsten Anmeldung</li>
              <li>Erstellt, entfernt und verwaltet Benutzerkonten</li>
              <li>Ändert die Mitgliedschaft einer Gruppe</li>
            </>
          ) : (
            <>
              <li>Reset user passwords and force password change at next logon</li>
              <li>Create, delete, and manage user accounts</li>
              <li>Modify the membership of a group</li>
            </>
          )}
        </ul>
        <p>
          {de
            ? "Damit das Maschinenkonto die neue Gruppe sofort im Kerberos-Ticket trägt (sonst erst nach einem Neustart des DC), in einer Eingabeaufforderung als Administrator:"
            : "So the machine account carries the new group in its Kerberos ticket right away (otherwise only after a DC reboot), in an elevated command prompt:"}
        </p>
        <Code>klist -li 0x3e7 purge</Code>
        <p className="text-xs text-slate-600">
          {de
            ? "Keine weiteren Rechte, keine Domänen-Admin-Gruppe. Konten mit adminCount=1 schützt AdminSDHolder; der Agent lässt sie zusätzlich selbst in Ruhe."
            : "No further rights, no Domain Admins membership. Accounts with adminCount=1 are protected by AdminSDHolder; the agent also refuses to touch them itself."}
        </p>
      </Step>

      <Step n={4} title={de ? "Netz vom DC aus prüfen" : "Check the network from the DC"}>
        <Code>{`Test-NetConnection ${host} -Port 46200`}</Code>
        <p>
          {de
            ? "Erwartet: TcpTestSucceeded : True. Löst der Name nicht auf, gehört er in den DNS (oder in C:\\Windows\\System32\\drivers\\etc\\hosts) — nie die IP in den Befehl, das Zertifikat der Plattform gilt nur für den Namen."
            : "Expected: TcpTestSucceeded : True. If the name doesn't resolve, add it to DNS (or C:\\Windows\\System32\\drivers\\etc\\hosts) — never put the IP into the command, the platform certificate is only valid for the name."}
        </p>
      </Step>

      <Step n={5} title={de ? "Dateien auf den DC holen" : "Copy the files to the DC"}>
        <p>
          {de ? "Unter „Agent herunterladen“ das MSI " : "Under “Agent herunterladen” download the MSI "}
          <Mono>{msi}</Mono>
          {hasCa === false
            ? de
              ? " herunterladen und nach "
              : " and copy it to "
            : de
              ? " und das Stammzertifikat root.pem herunterladen und beide nach "
              : " and the root certificate root.pem and copy both to "}
          <Mono>C:\Temp</Mono>
          {de ? " auf dem DC kopieren. Dann die Prüfsumme vergleichen:" : " on the DC. Then compare the checksum:"}
        </p>
        <Code>
          {`Get-FileHash C:\\Temp\\${msi} -Algorithm SHA256\n` + `Unblock-File C:\\Temp\\${msi}`}
        </Code>
        <p>
          {de
            ? "Der Hash muss mit dem SHA-256 unter dem Paket übereinstimmen. Unblock-File entfernt die Markierung „aus dem Internet“."
            : "The hash must match the SHA-256 shown below the package. Unblock-File removes the “downloaded from the internet” mark."}
          {hasCa !== false &&
            (de
              ? " Für root.pem: SHA-256 im Cockpit mit dem Fingerprint vergleichen, den Windows beim Öffnen der Datei (umbenannt auf .crt) unter Details zeigt — oder mit dem, den Vita Brevis telefonisch nennt."
              : " For root.pem: compare the SHA-256 in the cockpit with the fingerprint Windows shows under Details when you open the file (renamed to .crt) — or with the one Vita Brevis reads to you by phone.")}
        </p>
      </Step>

      <Step n={6} title={de ? "Installieren" : "Install"}>
        <p>{de ? "Eingabeaufforderung als Administrator:" : "Elevated command prompt:"}</p>
        <Code>{`msiexec /i C:\\Temp\\${msi} /l*v C:\\Temp\\magister-msi.log`}</Code>
        <p>
          {de
            ? "Das MSI ist noch unsigniert: SmartScreen warnt („Weitere Informationen → Trotzdem ausführen“), unter AppLocker/WDAC braucht es eine Ausnahme. Der Dienst „Magister Connector-Agent“ (MagisterConnector, LocalSystem) wird eingerichtet, aber absichtlich noch nicht gestartet."
            : "The MSI is not signed yet: SmartScreen warns (“More info → Run anyway”), AppLocker/WDAC need an exception. The service “Magister Connector-Agent” (MagisterConnector, LocalSystem) is installed but deliberately not started yet."}
        </p>
        <p>
          {de
            ? "Danach eine neue Eingabeaufforderung öffnen — die alte kennt den PATH-Eintrag noch nicht. Am einfachsten: Startmenü → „Magister Connector“ → „Connector-Agent - Eingabeaufforderung“, Rechtsklick „Als Administrator ausführen“."
            : "Then open a new command prompt — the old one doesn't know the PATH entry yet. Easiest: Start menu → “Magister Connector” → “Connector-Agent - Eingabeaufforderung”, right-click “Run as administrator”."}
        </p>
      </Step>

      <Step n={7} title={de ? "Einmal-Token erzeugen und anmelden" : "Create the one-time token and enroll"}>
        <p>
          {de
            ? "Hier im Cockpit unter „Agenten“ den Namen des DC eintragen (z. B. dc01.schule.local) und „Einmal-Token erzeugen“. Das Token durch Vita Brevis per Telefon, Signal oder persönlich weitergeben — nicht per E-Mail, nicht ins Ticket. Es gilt 24 Stunden und genau einmal. Dann in der Administrator-Eingabeaufforderung aus Schritt 6:"
            : "Here in the cockpit under “Agenten” enter the DC's name (e.g. dc01.school.local) and click “Einmal-Token erzeugen”. Vita Brevis passes the token on by phone, Signal or in person — not by e-mail, not in a ticket. It is valid for 24 hours and exactly once. Then in the elevated prompt from step 6:"}
        </p>
        <Code>{enrollCmd}</Code>
        <p>
          {de
            ? "Der Agent fragt „Einmal-Token:“ — dort einfügen (Rechtsklick fügt ein) und Enter. Nicht als --token angeben: sonst steht es in der Befehlsgeschichte und der Prozessliste."
            : "The agent asks “Einmal-Token:” — paste it there (right-click pastes) and press Enter. Don't pass it as --token: it would end up in the command history and process list."}
          {hasCa === null &&
            (de
              ? " Ob --ca nötig ist, zeigt „Agent herunterladen“: steht dort ein Stammzertifikat, ja; sonst den Teil weglassen."
              : " Whether --ca is needed is shown under “Agent herunterladen”: if a root certificate is listed, yes; otherwise drop that part.")}
        </p>
        <p>
          {de
            ? "Der Agent erzeugt seinen Schlüssel lokal, meldet sich an, zeigt „Anmeldung erfolgreich“ mit dem SPKI-Fingerprint, holt die Einstellungen aus dem Cockpit und startet den Dienst („Dienst: … gestartet“)."
            : "The agent creates its key locally, enrolls, prints “Anmeldung erfolgreich” with the SPKI fingerprint, fetches its settings from the cockpit and starts the service (“Dienst: … gestartet”)."}
        </p>
        <p className="font-medium text-slate-800">
          {de
            ? "Fingerprint vergleichen: die ersten 16 Zeichen müssen mit der Spalte „SPKI“ in der Agententabelle übereinstimmen (Maus darüber zeigt ihn ganz). Weicht er ab, Agent sofort widerrufen und mit neuem Token neu anmelden."
            : "Compare the fingerprint: the first 16 characters must match the “SPKI” column in the agent table (hover shows it in full). If it differs, revoke the agent immediately and enroll again with a new token."}
        </p>
      </Step>

      <Step n={8} title={de ? "Prüfen" : "Verify"}>
        <Code>{`magister-connector check\nsc query MagisterConnector`}</Code>
        <p>
          {de
            ? "check verändert nichts und meldet Endpunkt, Rechte des Zustandsverzeichnisses, Anmeldung, Kanal (Port 46200), Cockpit-Konfiguration, OU-Freigabe und LDAPS zum DC. Der Dienst muss RUNNING sein."
            : "check changes nothing and reports endpoint, state directory permissions, enrollment, channel (port 46200), cockpit configuration, allowed OUs and LDAPS to the DC. The service must be RUNNING."}
        </p>
        <p>
          {de
            ? "Im Cockpit: der Agent steht in der Tabelle mit Zustand „active“ und „Zuletzt gesehen“ von eben. Dann oben „Verbindung testen“ — erwartet: „AD antwortet, Kerberos-Anmeldung … gelungen“. Ob die Delegation aus Schritt 3 reicht, zeigt der erste echte Auftrag (z. B. ein Passwort-Reset im Magister)."
            : "In the cockpit: the agent shows up in the table with state “active” and a recent “Zuletzt gesehen”. Then click “Verbindung testen” above — expected: “AD antwortet, Kerberos-Anmeldung … gelungen”. Whether the delegation from step 3 is sufficient shows with the first real job (e.g. a password reset in Magister)."}
        </p>
      </Step>

      <Step n={9} title={de ? "Später: Aktualisieren und Entfernen" : "Later: update and remove"}>
        <Code>
          {`magister-connector update            ${de ? "# neue Fassung holen, Dienst neu starten" : "# fetch new version, restart service"}\n` +
            `magister-connector uninstall         ${de ? "# abmelden, Schlüssel löschen, Programm entfernen" : "# deregister, delete keys, remove program"}`}
        </Code>
        <p>
          {de
            ? "Immer als Administrator. Nicht über „Apps & Features“ deinstallieren — dann bleiben Anmeldung und Schlüssel in C:\\ProgramData\\Magister Connector liegen. Das Zertifikat erneuert sich alle 90 Tage selbst; dafür ist nichts zu tun. Server ersetzt: alten Agenten hier widerrufen, auf dem neuen DC ab Schritt 3."
            : "Always as administrator. Don't uninstall via “Apps & Features” — enrollment and keys would remain in C:\\ProgramData\\Magister Connector. The certificate renews itself every 90 days; nothing to do. Server replaced: revoke the old agent here, start at step 3 on the new DC."}
        </p>
      </Step>
    </ol>
  );
}

const TROUBLE: { msg: string; de: string; en: string }[] = [
  {
    msg: "Das Zertifikat der Plattform gilt nicht für …",
    de: "Im Endpunkt steht eine IP oder ein anderer Name. Genau den Namen aus Schritt 7 verwenden; der Port ist offen.",
    en: "The endpoint contains an IP or another name. Use exactly the name from step 7; the port is open.",
  },
  {
    msg: "… stammt von einer Stelle, der dieser Server nicht vertraut",
    de: "--ca C:\\Temp\\root.pem fehlt, oder ein Proxy bricht TLS auf (Ausnahme für den Connector-Namen einrichten).",
    en: "--ca C:\\Temp\\root.pem is missing, or a proxy inspects TLS (add an exception for the connector name).",
  },
  {
    msg: "Verbindung zu … abgewiesen / Keine Antwort von …",
    de: "Firewall: ausgehend TCP 46200 zum Connector-Namen freigeben (Schritt 4).",
    en: "Firewall: allow outbound TCP 46200 to the connector name (step 4).",
  },
  {
    msg: "Der Name … lässt sich nicht auflösen",
    de: "DNS-Eintrag oder hosts-Datei fehlt.",
    en: "DNS record or hosts file entry missing.",
  },
  {
    msg: "'magister-connector' wird nicht erkannt / is not recognized",
    de: "Alte Eingabeaufforderung: neue öffnen (Schritt 6) oder \"C:\\Program Files\\Magister Connector\\magister-connector.exe\" mit vollem Pfad aufrufen.",
    en: "Old command prompt: open a new one (step 6) or call \"C:\\Program Files\\Magister Connector\\magister-connector.exe\" with the full path.",
  },
  {
    msg: "Das Einmal-Token wurde abgelehnt …",
    de: "Neues Einmal-Token erzeugen. Jedes gilt 24 Stunden und nur einmal.",
    en: "Create a new one-time token. Each is valid for 24 hours and only once.",
  },
  {
    msg: "In … liegt bereits eine Anmeldung",
    de: "Der DC war schon angemeldet. Alten Agenten hier widerrufen, dann magister-connector uninstall --paket-behalten und erneut enroll.",
    en: "The DC was already enrolled. Revoke the old agent here, then magister-connector uninstall --paket-behalten and enroll again.",
  },
  {
    msg: "Dienst: nicht gestartet …",
    de: "sc start MagisterConnector; startet er nicht, steht der Grund im agent.log und in der Ereignisanzeige — meist mit dem Befehl, der es behebt.",
    en: "sc start MagisterConnector; if it won't start, the reason is in agent.log and the Event Viewer — usually with the command that fixes it.",
  },
  {
    msg: "insufficientAccessRights",
    de: "Delegation aus Schritt 3 fehlt auf dieser OU, oder das Ticket kennt die Gruppe noch nicht (klist -li 0x3e7 purge).",
    en: "Delegation from step 3 missing on this OU, or the ticket doesn't know the group yet (klist -li 0x3e7 purge).",
  },
  {
    msg: "… ausserhalb der erlaubten OUs",
    de: "Die OU ist im Cockpit unter „Freigabe im AD“ nicht eingetragen.",
    en: "The OU is not listed in the cockpit under “Freigabe im AD”.",
  },
  {
    msg: "Rechte des Zustandsverzeichnisses",
    de: "Andere könnten den privaten Schlüssel lesen. Die Meldung enthält die icacls-Zeile, die es richtet.",
    en: "Others could read the private key. The message contains the icacls line that fixes it.",
  },
];

function Troubleshooting({ lang }: { lang: Lang }) {
  const de = lang === "de";
  return (
    <div>
      <div className="mb-1 font-medium">{de ? "Wenn etwas nicht geht" : "Troubleshooting"}</div>
      <p className="mb-1 text-xs text-slate-600">
        {de ? "Protokoll: " : "Log: "}
        <Mono>C:\ProgramData\Magister Connector\agent.log</Mono>
        {de
          ? " · Ereignisanzeige → Anwendung, Quelle „MagisterConnector“ · MSI-Protokoll: "
          : " · Event Viewer → Application, source “MagisterConnector” · MSI log: "}
        <Mono>C:\Temp\magister-msi.log</Mono>
      </p>
      <table className="w-full text-left text-xs">
        <tbody>
          {TROUBLE.map((row) => (
            <tr key={row.msg} className="border-t border-sky-200 align-top">
              <td className="py-1 pr-3 font-mono">{row.msg}</td>
              <td className="py-1">{row[lang]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-600">
        {de
          ? "Die vollständige Anleitung liegt nach der Installation auch auf dem DC: Startmenü → „Magister Connector“ → „Installationsanleitung“."
          : "After installation the full guide (German) is also on the DC: Start menu → “Magister Connector” → “Installationsanleitung”."}
      </p>
    </div>
  );
}
