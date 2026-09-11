import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { logout, whoami } from "./api/consoleAuth";
import { ConsoleLogin } from "./components/ConsoleLogin";
import { href, useRoute } from "./lib/nav";
import { Instances } from "./routes/Instances";
import { Templates } from "./routes/Templates";
import { TenantDetail } from "./routes/TenantDetail";
import { Tenants } from "./routes/Tenants";

/**
 * Der Notzugang.
 *
 * Seit ADR-0020 ist der reguläre Weg Zertifikat plus zweiter Faktor. Der
 * Bootstrap-Token bleibt trotzdem: er ist der einzige Weg in eine frisch
 * ausgerollte Konsole, in der noch kein Operator eingetragen ist — und in eine
 * Entwicklungsumgebung, die keine Client-Zertifikate prüft.
 *
 * Er liegt in `sessionStorage` und nicht in `localStorage`: damit ist er weg,
 * wenn der Tab zugeht, und überlebt kein Wochenende auf einem Bildschirm im
 * Büro. Im Protokoll heisst er `bootstrap-token` und nicht wie eine Person.
 */
function BootstrapTokenBox({ onSet }: { onSet: (token: string) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(sessionStorage.getItem("cockpit_token") ?? "");
  const [saved, setSaved] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-slate-500 underline"
      >
        Notzugang mit Bootstrap-Token
      </button>
    );
  }

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        sessionStorage.setItem("cockpit_token", value);
        setSaved(true);
        // `onSet` und nicht nur `invalidateQueries`: der Abruf liefert
        // dieselbe Antwort wie vorher („unbekanntes Zertifikat"), React Query
        // sieht unveraenderte Daten, und ohne Zustandsaenderung baut App sich
        // nicht neu auf. Gemessen: der Token war gesetzt, und die
        // Anmeldemaske blieb stehen.
        onSet(value);
        void qc.invalidateQueries();
      }}
    >
      <input
        type="password"
        placeholder="Bootstrap-Token"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setSaved(false);
        }}
        className="rounded border px-2 py-1 text-sm"
      />
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-sm text-white">
        {saved ? "Gesetzt" : "Setzen"}
      </button>
    </form>
  );
}

function NavLink({ to, label, active }: { to: string; label: string; active: boolean }) {
  return (
    <a
      href={to}
      className={`rounded px-2 py-1 text-sm ${
        active ? "bg-slate-200 font-medium" : "text-slate-600 hover:text-slate-900"
      }`}
    >
      {label}
    </a>
  );
}

/** Wer angemeldet ist — und der Weg heraus. */
function Identity({
  upn,
  name,
  onLoggedOut,
}: {
  upn: string | null;
  name: string | null;
  onLoggedOut: () => void;
}) {
  const qc = useQueryClient();
  const logoutM = useMutation({
    mutationFn: logout,
    // `resetQueries` und nicht `invalidateQueries`: nach dem Abmelden sollen
    // die Antworten weg sein und nicht neu geholt werden. Sonst stünden die
    // Kundendaten der letzten Ansicht noch im Speicher des Browsers, während
    // die Anmeldemaske darüber liegt.
    onSettled: () => {
      // Auch den Notzugang wegwerfen: „Abmelden" soll draussen heissen. Ein
      // liegengebliebener Token haette die Anwendung gleich wieder geoeffnet
      // — unter dem Namen `bootstrap-token`.
      onLoggedOut();
      return qc.resetQueries();
    },
  });

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-slate-600" title={upn ?? undefined}>
        {name ?? upn}
      </span>
      <button
        type="button"
        onClick={() => logoutM.mutate()}
        disabled={logoutM.isPending}
        className="rounded border px-2 py-1 text-xs disabled:opacity-50"
      >
        Abmelden
      </button>
    </div>
  );
}

export function App() {
  const route = useRoute();
  // `retry: false`: die Frage „welcher Schritt fehlt“ hat immer eine Antwort;
  // wenn sie scheitert, ist die Konsole nicht erreichbar, und ein zweiter
  // Versuch macht die Anmeldemaske nur langsamer.
  const whoQ = useQuery({ queryKey: ["whoami"], queryFn: whoami, retry: false });

  // Der Notzugang: ein gesetzter Token trägt auch ohne Sitzung. Als Zustand
  // und nicht als Blick in den `sessionStorage` beim Zeichnen — sonst merkt
  // die Ansicht nicht, dass gerade einer gesetzt wurde.
  const [token, setToken] = useState(() => sessionStorage.getItem("cockpit_token") ?? "");

  function forgetToken(): void {
    sessionStorage.removeItem("cockpit_token");
    setToken("");
  }

  const who = whoQ.data;
  const signedIn = who?.stage === "authenticated";
  // Getrennt ausgewiesen, damit niemand den Notzugang für eine Anmeldung hält.
  const viaToken = !signedIn && token !== "";

  if (whoQ.isPending) {
    return <p className="p-6 text-sm text-slate-500">Einen Moment…</p>;
  }

  if (!signedIn && !viaToken) {
    return (
      <div>
        <ConsoleLogin
          who={who ?? { stage: "unknown_certificate", upn: null, name: null, expires_at: null }}
        />
        <div className="mx-auto max-w-xl px-6 pb-6">
          <BootstrapTokenBox onSet={setToken} />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex items-baseline gap-4">
          <span className="text-lg font-semibold">Vita Brevis Cockpit</span>
          <nav className="flex gap-1">
            <NavLink
              to={href({ view: "tenants" })}
              label="Kunden"
              active={route.view === "tenants" || route.view === "tenant"}
            />
            <NavLink
              to={href({ view: "instances" })}
              label="Instanzen"
              active={route.view === "instances"}
            />
            <NavLink
              to={href({ view: "templates" })}
              label="Vorlagen"
              active={route.view === "templates"}
            />
          </nav>
        </div>
        {signedIn && who ? (
          <Identity upn={who.upn} name={who.name} onLoggedOut={forgetToken} />
        ) : (
          <BootstrapTokenBox onSet={setToken} />
        )}
      </header>

      {viaToken && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded border border-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            Notzugang mit Bootstrap-Token. Was jetzt geschieht, steht im Protokoll des
            Kunden als <code className="font-mono">bootstrap-token</code> — ohne Namen.
            Für die tägliche Arbeit ist das der falsche Weg.
          </p>
          {/*
            Der Weg zurück zur Anmeldemaske. Ohne ihn gibt es keinen: ein
            gesetzter Token trägt die Anwendung, und die Maske erscheint erst
            wieder, wenn der Tab zugeht. Wer auf einer frischen Konsole den
            Token setzt und dann seinen zweiten Faktor einrichten will, sass
            sonst fest.
          */}
          <button
            type="button"
            onClick={forgetToken}
            className="shrink-0 rounded border border-amber-500 px-2 py-1 text-xs"
          >
            Notzugang beenden und anmelden
          </button>
        </div>
      )}

      {route.view === "tenants" && <Tenants />}
      {route.view === "instances" && <Instances />}
      {route.view === "templates" && <Templates />}
      {route.view === "tenant" && <TenantDetail tenantId={route.id} tab={route.tab} />}
    </div>
  );
}
