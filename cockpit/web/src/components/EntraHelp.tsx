import { useState, type ReactNode } from "react";

type Lang = "de" | "en";

/** Knopf neben der Überschrift „Entra ID (Anmeldung)“. `type="button"`: er steht im Einstellungsformular. */
export function EntraHelpButton({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="rounded border px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
    >
      {open ? "Hilfe schliessen / Close help" : "? Hilfe / Help"}
    </button>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="my-1 overflow-x-auto whitespace-pre-wrap break-all rounded bg-slate-900 px-2 py-1 font-mono text-xs text-slate-100">
      {children}
    </pre>
  );
}

function Path({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs text-slate-800">{children}</span>;
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="space-y-1">
      <div className="font-medium">
        {n}. {title}
      </div>
      <div className="space-y-1 text-slate-700">{children}</div>
    </li>
  );
}

/**
 * Schritt-für-Schritt-Anleitung für die App-Registrierung in Entra und den
 * ersten Test der Anmeldung — auf Deutsch und Englisch, mit den Werten dieses
 * Kunden eingesetzt, soweit sie schon bekannt sind.
 *
 * Die Pfade folgen dem Entra Admin Center (entra.microsoft.com). Das Cockpit
 * ist sonst nur deutsch; die englische Fassung ist für Kunden-IT, die ihr
 * Portal englisch eingestellt hat und die Menüs so wiederfinden muss.
 */
export function EntraHelp({
  redirectUri,
  hostname,
  tenantId,
  clientId,
}: {
  redirectUri: string;
  hostname: string;
  tenantId: string;
  clientId: string;
}) {
  const [lang, setLang] = useState<Lang>("de");
  const host = hostname || "<host>";
  const redirect = redirectUri || `https://${host}/api/auth/callback`;
  const tid = tenantId.trim() || "<tenant-id>";
  const cid = clientId.trim() || "<client-id>";
  const props = { host, redirect, tid, cid };

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
              (lang === l
                ? "bg-sky-700 text-white"
                : "border bg-white text-slate-700")
            }
          >
            {l === "de" ? "Deutsch" : "English"}
          </button>
        ))}
      </div>
      {lang === "de" ? <German {...props} /> : <English {...props} />}
    </div>
  );
}

type Values = { host: string; redirect: string; tid: string; cid: string };

function logCommand(host: string) {
  return (
    `cd /opt/magister\n` +
    `docker compose --project-directory deploy/compose logs --since 15m magister-api \\\n` +
    `  | grep -iE "entra|oidc"\n` +
    `# ${host}`
  );
}

function German({ host, redirect, tid, cid }: Values) {
  return (
    <div className="space-y-3">
      <p>
        <strong>Voraussetzungen:</strong> Konto mit der Rolle{" "}
        <em>Anwendungsadministrator</em> (oder{" "}
        <em>Cloudanwendungsadministrator</em>) im Entra-Verzeichnis des Kunden.
        Der AD-Abgleich ist gelaufen, und die Testperson steht in Magister — ihr
        UPN in Entra muss dem UPN im lokalen AD entsprechen (Entra Connect/Cloud
        Sync synchronisiert ihn so).
      </p>
      <ol className="space-y-3">
        <Step n={1} title="App registrieren">
          <div>
            <Path>
              entra.microsoft.com → Identität → Anwendungen →
              App-Registrierungen → Neue Registrierung
            </Path>
          </div>
          <ul className="list-disc pl-5">
            <li>
              Name: z. B. <Path>Magister ({host})</Path>
            </li>
            <li>
              Unterstützte Kontotypen:{" "}
              <em>Nur Konten in diesem Organisationsverzeichnis</em> (Einzelner
              Mandant)
            </li>
            <li>
              Umleitungs-URI: Plattform <strong>Web</strong> (nicht „SPA“),
              Adresse genau so:
            </li>
          </ul>
          <Code>{redirect}</Code>
          <div>
            → <em>Registrieren</em>.
          </div>
        </Step>
        <Step n={2} title="IDs übernehmen">
          <div>
            Auf der Seite <Path>Übersicht</Path> der neuen App:
          </div>
          <ul className="list-disc pl-5">
            <li>
              <em>Verzeichnis-ID (Mandant)</em> → hier in{" "}
              <strong>Verzeichnis-(Tenant-)Id</strong>
            </li>
            <li>
              <em>Anwendungs-ID (Client)</em> → hier in{" "}
              <strong>Anwendungs-(Client-)Id</strong>
            </li>
          </ul>
          <div>
            Die Umleitungs-URI erscheint im Cockpit erst, wenn die Tenant-Id
            eingetragen ist, und wird nur dann gespeichert.
          </div>
        </Step>
        <Step n={3} title="Client-Secret erzeugen und versiegeln">
          <div>
            <Path>
              Zertifikate &amp; Geheimnisse → Geheime Clientschlüssel → Neuer
              geheimer Clientschlüssel
            </Path>
          </div>
          <div>
            Ablauf wählen (z. B. 12 Monate, im Kalender notieren). Danach die
            Spalte <strong>Wert</strong> kopieren — <em>nicht</em> die
            „Geheimnis-ID“. Der Wert ist nur jetzt sichtbar.
          </div>
          <div>
            Hier unten in <strong>Client-Secret</strong> einfügen →{" "}
            <strong>Versiegeln</strong>. Das Secret verlässt das Cockpit nur
            verschlüsselt für diese Installation.
          </div>
        </Step>
        <Step n={4} title="API-Berechtigungen">
          <div>
            <Path>
              API-Berechtigungen → Berechtigung hinzufügen → Microsoft Graph →
              Delegierte Berechtigungen
            </Path>
          </div>
          <div>
            <Path>openid</Path>, <Path>profile</Path>, <Path>email</Path> (meist
            ist <Path>User.Read</Path> schon da; darf bleiben) → danach{" "}
            <em>Administratorzustimmung für … erteilen</em>.
          </div>
          <div>
            Unter <Path>Authentifizierung</Path> braucht es{" "}
            <strong>keine</strong> Häkchen bei „Zugriffstoken“ oder „ID-Token“
            (implizit) — Magister nutzt Autorisierungscode mit PKCE.
          </div>
        </Step>
        <Step n={5} title="Zugriff einschränken (empfohlen)">
          <div>
            <Path>
              Unternehmensanwendungen → Magister ({host}) → Eigenschaften →
              Zuweisung erforderlich = Ja
            </Path>
            , dann unter <Path>Benutzer und Gruppen</Path> die
            Lehrpersonen-/Admin-Gruppe zuweisen.
          </div>
          <div>
            MFA kommt aus dem bedingten Zugriff:{" "}
            <Path>Schutz → Bedingter Zugriff → Neue Richtlinie</Path>,
            Zielressource diese App, Gewähren „Mehrstufige Authentifizierung
            erforderlich“.
          </div>
        </Step>
        <Step n={6} title="In Magister freischalten">
          <div>
            Abschnitt <strong>Zugang</strong>: unter{" "}
            <em>Erste Administratoren (UPN)</em> den UPN der Person eintragen,
            die als erste Admin-Rechte bekommt (z. B.{" "}
            <Path>it.admin@schule.ch</Path>). <em>Scopes</em> leer lassen ergibt{" "}
            <Path>openid profile email</Path>.
          </div>
          <div>
            → <strong>Einstellungen speichern</strong>. Nach dem nächsten
            Abgleich zeigt die Übersicht unter Zustand{" "}
            <em>Entra-Client-Secret: gesetzt</em>.
          </div>
        </Step>
        <Step n={7} title="Testen">
          <div>
            Ist OIDC in der Installation aktiv? Erwartet:{" "}
            <Path>"oidc_enabled": true</Path>
          </div>
          <Code>curl -s https://{host}/api/auth/capabilities</Code>
          <div>
            Privates Browserfenster → <Path>https://{host}/login</Path> →{" "}
            <em>Mit Entra ID anmelden</em>. Nach der Anmeldung bei Microsoft
            landet man im Portal. Im Portal unter{" "}
            <Path>Administration → Audit-Log</Path> stehen <Path>login</Path>{" "}
            und beim ersten Admin <Path>role_granted</Path>.
          </div>
          <div>Prüfen, ob Entra die richtige App kennt (Tenant {tid}):</div>
          <Code>
            {`curl -s https://login.microsoftonline.com/${tid}/v2.0/.well-known/openid-configuration | head -c 300`}
          </Code>
          <div>Fehler auf dem Server (dev01, im Ordner der Installation):</div>
          <Code>{logCommand(host)}</Code>
          <div>
            Direkter Test der App-Registrierung (öffnet die Microsoft-Anmeldung;
            endet mit „Umleitung“ auf Magister, ein Fehler dort ist hier egal):
          </div>
          <Code>
            {`https://login.microsoftonline.com/${tid}/oauth2/v2.0/authorize?client_id=${cid}&response_type=code&scope=openid&redirect_uri=${encodeURIComponent(redirect)}`}
          </Code>
        </Step>
      </ol>
      <Troubleshooting lang="de" />
    </div>
  );
}

function English({ host, redirect, tid, cid }: Values) {
  return (
    <div className="space-y-3">
      <p>
        <strong>Prerequisites:</strong> an account with the{" "}
        <em>Application Administrator</em> (or{" "}
        <em>Cloud Application Administrator</em>) role in the customer's Entra
        directory. The AD sync has run and the test person exists in Magister —
        their UPN in Entra must match the on-premises AD UPN (Entra
        Connect/Cloud Sync keeps it that way).
      </p>
      <ol className="space-y-3">
        <Step n={1} title="Register the app">
          <div>
            <Path>
              entra.microsoft.com → Identity → Applications → App registrations
              → New registration
            </Path>
          </div>
          <ul className="list-disc pl-5">
            <li>
              Name: e.g. <Path>Magister ({host})</Path>
            </li>
            <li>
              Supported account types:{" "}
              <em>Accounts in this organizational directory only</em> (Single
              tenant)
            </li>
            <li>
              Redirect URI: platform <strong>Web</strong> (not “SPA”), exactly:
            </li>
          </ul>
          <Code>{redirect}</Code>
          <div>
            → <em>Register</em>.
          </div>
        </Step>
        <Step n={2} title="Copy the IDs">
          <div>
            On the new app's <Path>Overview</Path> page:
          </div>
          <ul className="list-disc pl-5">
            <li>
              <em>Directory (tenant) ID</em> → here into{" "}
              <strong>Verzeichnis-(Tenant-)Id</strong>
            </li>
            <li>
              <em>Application (client) ID</em> → here into{" "}
              <strong>Anwendungs-(Client-)Id</strong>
            </li>
          </ul>
          <div>
            The redirect URI only appears in the cockpit (and is only saved)
            once the tenant ID is filled in.
          </div>
        </Step>
        <Step n={3} title="Create and seal the client secret">
          <div>
            <Path>
              Certificates &amp; secrets → Client secrets → New client secret
            </Path>
          </div>
          <div>
            Pick an expiry (e.g. 12 months, put it in the calendar). Copy the{" "}
            <strong>Value</strong> column — <em>not</em> the “Secret ID”. The
            value is shown only once.
          </div>
          <div>
            Paste it below into <strong>Client-Secret</strong> →{" "}
            <strong>Versiegeln</strong> (seal). The secret only leaves the
            cockpit encrypted for this installation.
          </div>
        </Step>
        <Step n={4} title="API permissions">
          <div>
            <Path>
              API permissions → Add a permission → Microsoft Graph → Delegated
              permissions
            </Path>
          </div>
          <div>
            <Path>openid</Path>, <Path>profile</Path>, <Path>email</Path> (
            <Path>User.Read</Path> is usually already there; leave it) → then{" "}
            <em>Grant admin consent for …</em>.
          </div>
          <div>
            Under <Path>Authentication</Path> you need <strong>no</strong>{" "}
            “Access tokens” or “ID tokens” (implicit) checkboxes — Magister uses
            authorization code with PKCE.
          </div>
        </Step>
        <Step n={5} title="Restrict access (recommended)">
          <div>
            <Path>
              Enterprise applications → Magister ({host}) → Properties →
              Assignment required = Yes
            </Path>
            , then assign the teacher/admin group under{" "}
            <Path>Users and groups</Path>.
          </div>
          <div>
            MFA comes from Conditional Access:{" "}
            <Path>Protection → Conditional Access → New policy</Path>, target
            resource this app, grant “Require multifactor authentication”.
          </div>
        </Step>
        <Step n={6} title="Enable in Magister">
          <div>
            Section <strong>Zugang</strong>: under{" "}
            <em>Erste Administratoren (UPN)</em> enter the UPN of the person who
            gets admin rights first (e.g. <Path>it.admin@school.ch</Path>).
            Leaving <em>Scopes</em> empty means{" "}
            <Path>openid profile email</Path>.
          </div>
          <div>
            → <strong>Einstellungen speichern</strong> (save). After the next
            reconcile the overview shows <em>Entra-Client-Secret: gesetzt</em>{" "}
            under status.
          </div>
        </Step>
        <Step n={7} title="Test">
          <div>
            Is OIDC active in the installation? Expected:{" "}
            <Path>"oidc_enabled": true</Path>
          </div>
          <Code>curl -s https://{host}/api/auth/capabilities</Code>
          <div>
            Private browser window → <Path>https://{host}/login</Path> →{" "}
            <em>Sign in with Entra ID</em>. After the Microsoft sign-in you land
            in the portal. In the portal under <Path>Admin → Audit Log</Path>{" "}
            you see <Path>login</Path> and, for the first admin,{" "}
            <Path>role_granted</Path>.
          </div>
          <div>Check that Entra knows the tenant ({tid}):</div>
          <Code>
            {`curl -s https://login.microsoftonline.com/${tid}/v2.0/.well-known/openid-configuration | head -c 300`}
          </Code>
          <div>Server-side errors (dev01, in the installation folder):</div>
          <Code>{logCommand(host)}</Code>
          <div>
            Direct test of the app registration (opens the Microsoft sign-in;
            ends with a redirect to Magister, an error there does not matter for
            this test):
          </div>
          <Code>
            {`https://login.microsoftonline.com/${tid}/oauth2/v2.0/authorize?client_id=${cid}&response_type=code&scope=openid&redirect_uri=${encodeURIComponent(redirect)}`}
          </Code>
        </Step>
      </ol>
      <Troubleshooting lang="en" />
    </div>
  );
}

const TROUBLE: { code: string; de: string; en: string }[] = [
  {
    code: "AADSTS50011",
    de: "Umleitungs-URI stimmt nicht. In der App-Registrierung unter Authentifizierung → Web genau die URI oben eintragen (https, kein Schrägstrich am Ende).",
    en: "Redirect URI mismatch. Under Authentication → Web enter exactly the URI above (https, no trailing slash).",
  },
  {
    code: "AADSTS7000215",
    de: "Falsches Client-Secret — meist die Geheimnis-ID statt des Werts. Neues Secret erzeugen, Wert versiegeln. Portal zeigt „oidc_token_exchange_failed“.",
    en: "Invalid client secret — usually the Secret ID instead of the Value. Create a new secret, seal the value. Portal shows “oidc_token_exchange_failed”.",
  },
  {
    code: "AADSTS7000222",
    de: "Client-Secret abgelaufen. Neues erzeugen und versiegeln.",
    en: "Client secret expired. Create a new one and seal it.",
  },
  {
    code: "AADSTS700016",
    de: "Client-Id unbekannt in diesem Verzeichnis — Tenant-Id und Client-Id vertauscht oder aus einem anderen Verzeichnis.",
    en: "Client ID not found in this directory — tenant and client ID swapped or from another directory.",
  },
  {
    code: "AADSTS50105",
    de: "Benutzer ist der App nicht zugewiesen („Zuweisung erforderlich“ = Ja). Unter Benutzer und Gruppen zuweisen.",
    en: "User not assigned to the app (“Assignment required” = Yes). Assign under Users and groups.",
  },
  {
    code: "AADSTS65001",
    de: "Zustimmung fehlt. Unter API-Berechtigungen die Administratorzustimmung erteilen.",
    en: "Consent missing. Grant admin consent under API permissions.",
  },
  {
    code: "user_not_synced",
    de: "Anmeldung bei Microsoft gelang, aber Magister kennt die Person nicht: AD-Abgleich gelaufen? Liegt sie in einer Such-Basis? Stimmt der UPN in Entra mit dem UPN im AD überein?",
    en: "Microsoft sign-in worked but Magister doesn't know the person: has the AD sync run? Is the user inside a search base? Does the Entra UPN match the AD UPN?",
  },
  {
    code: "oidc_discovery_failed",
    de: "Magister erreicht Entra nicht oder die Tenant-Id ist falsch. Auf dem Server: curl auf die openid-configuration oben (Proxy/Firewall nach login.microsoftonline.com:443).",
    en: "Magister can't reach Entra or the tenant ID is wrong. On the server: curl the openid-configuration above (proxy/firewall to login.microsoftonline.com:443).",
  },
  {
    code: "oidc_enabled: false",
    de: "Tenant-Id, Client-Id oder Secret fehlen in der Installation. Gespeichert? Abgleich gelaufen (Übersicht → Zustand)?",
    en: "Tenant ID, client ID or secret missing in the installation. Saved? Reconcile done (overview → status)?",
  },
];

function Troubleshooting({ lang }: { lang: Lang }) {
  return (
    <div>
      <div className="mb-1 font-medium">
        {lang === "de" ? "Häufige Fehler" : "Common errors"}
      </div>
      <p className="mb-1 text-xs text-slate-600">
        {lang === "de"
          ? "AADSTS-Codes zeigt Microsoft auf der eigenen Anmeldeseite; scheitert erst der Code-Tausch (Secret), steht der Code im Server-Log (Befehl oben). Die Magister-Login-Seite nennt den Fehler mit Kurzcode."
          : "Microsoft shows AADSTS codes on its own sign-in page; if only the code exchange fails (secret), the code is in the server log (command above). The Magister login page names the error with a short code."}
      </p>
      <table className="w-full text-left text-xs">
        <tbody>
          {TROUBLE.map((row) => (
            <tr key={row.code} className="border-t border-sky-200 align-top">
              <td className="py-1 pr-3 font-mono whitespace-nowrap">
                {row.code}
              </td>
              <td className="py-1">{row[lang]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-600">
        {lang === "de"
          ? "Secret erneuern: in Entra ein neues erzeugen, hier versiegeln, nach dem Abgleich testen, erst dann das alte in Entra löschen."
          : "Rotating the secret: create a new one in Entra, seal it here, test after the reconcile, only then delete the old one in Entra."}
      </p>
    </div>
  );
}
