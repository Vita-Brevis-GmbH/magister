import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { href, useRoute } from "./lib/nav";
import { Instances } from "./routes/Instances";
import { TenantDetail } from "./routes/TenantDetail";
import { Tenants } from "./routes/Tenants";

/**
 * Der Token-Kasten.
 *
 * Bis zur Anmeldung über OIDC mit Hardware-Schlüssel (Entscheid E21) ist der
 * Bootstrap-Token der einzige Zugang. Er liegt in `sessionStorage` und nicht
 * in `localStorage`: damit ist er weg, wenn der Tab zugeht, und überlebt kein
 * Wochenende auf einem Bildschirm im Büro.
 */
function TokenBox() {
  const qc = useQueryClient();
  const [value, setValue] = useState(sessionStorage.getItem("cockpit_token") ?? "");
  const [saved, setSaved] = useState(false);

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        sessionStorage.setItem("cockpit_token", value);
        setSaved(true);
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

export function App() {
  const route = useRoute();

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
          </nav>
        </div>
        <TokenBox />
      </header>

      {route.view === "tenants" && <Tenants />}
      {route.view === "instances" && <Instances />}
      {route.view === "tenant" && <TenantDetail tenantId={route.id} tab={route.tab} />}
    </div>
  );
}
