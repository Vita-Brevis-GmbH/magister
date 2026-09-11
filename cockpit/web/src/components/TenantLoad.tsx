import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  relocateTenant,
  updateTenantLimits,
  type IsolationMode,
  type Tenant,
} from "../api/tenants";
import { ErrorBox } from "./ErrorBox";

/**
 * Die beiden Flächen, die ADR-0021 der Konsole gibt: Lastgrenzen (D3) und der
 * Verweis auf die Ablage (D5).
 *
 * Was hier **nicht** steht, ist die Migrationswelle. Die läuft auf dem
 * Anwendungsserver (`magister-cli tenants migrate`), weil nur dort die
 * Kunden-DSNs liegen — ADR-0021 D1 mit der Begründung. Der Reiter, der hier
 * einmal vorgesehen war, hätte einen Knopf gezeigt, den die Konsole nicht
 * drücken kann.
 */

const NUMBER_CLASS = "w-32 rounded border px-2 py-1 text-right font-mono text-sm";

function seconds(ms: number): string {
  return `${(ms / 1000).toLocaleString("de-CH", { maximumFractionDigits: 1 })} s`;
}

export function TenantLimitsSection({ tenant }: { tenant: Tenant }) {
  const qc = useQueryClient();
  // Vorbelegt mit den geltenden Werten — alle drei gehen bei jeder Änderung
  // mit (die API verlangt das), also muss das Formular sie kennen.
  const [statement, setStatement] = useState(String(tenant.statement_timeout_ms));
  const [idle, setIdle] = useState(String(tenant.idle_in_transaction_ms));
  const [connections, setConnections] = useState(String(tenant.connection_limit));
  const [reason, setReason] = useState("");

  const saveM = useMutation({
    mutationFn: () =>
      updateTenantLimits(tenant.id, {
        statement_timeout_ms: Number(statement),
        idle_in_transaction_ms: Number(idle),
        connection_limit: Number(connections),
        reason,
      }),
    onSuccess: () => {
      setReason("");
      void qc.invalidateQueries({ queryKey: ["tenant", tenant.id] });
      void qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-2 font-semibold">Lastgrenzen</h2>
      <p className="mb-3 text-xs text-slate-500">
        Sie hängen an der Mandantenrolle in Postgres, nicht am Anfragepfad: eine
        Abfrage, die zu lange läuft, bricht dort ab, wo sie Last macht — auch
        dann, wenn sie aus einem Hintergrundlauf kommt und durch keine
        Middleware ging. Gespeichert wird nur, was sich auch setzen liess;
        scheitert das <code className="font-mono">ALTER ROLE</code>, bleibt
        alles wie es war.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          saveM.mutate();
        }}
        className="space-y-3"
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Abfrage bricht ab nach (ms)</span>
            <input
              type="number"
              required
              min={1000}
              max={3600000}
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              className={NUMBER_CLASS}
            />
            <span className="mt-1 block text-xs text-slate-400">
              {seconds(tenant.statement_timeout_ms)} gilt
            </span>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">
              Offene Transaktion bricht ab nach (ms)
            </span>
            <input
              type="number"
              required
              min={1000}
              max={3600000}
              value={idle}
              onChange={(e) => setIdle(e.target.value)}
              className={NUMBER_CLASS}
            />
            <span className="mt-1 block text-xs text-slate-400">
              {seconds(tenant.idle_in_transaction_ms)} gilt
            </span>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Verbindungen</span>
            <input
              type="number"
              required
              min={10}
              max={1000}
              value={connections}
              onChange={(e) => setConnections(e.target.value)}
              className={NUMBER_CLASS}
            />
            <span className="mt-1 block text-xs text-slate-400">
              {tenant.connection_limit} gilt
            </span>
          </label>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Begründung (Pflicht)</span>
          <input
            required
            minLength={5}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Notenabschluss, Ticket 1234"
            className="w-full rounded border px-2 py-1"
          />
        </label>
        <p className="text-xs text-slate-500">
          Eine Grenze zu heben ist eine Entscheidung. Sie steht mit Namen und
          Grund im Protokoll der Konsole — sonst wäre in einem Jahr niemand mehr
          da, der sagen kann, warum dieser Kunde mehr darf als die anderen.
        </p>

        <button
          type="submit"
          disabled={saveM.isPending}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          {saveM.isPending ? "Läuft…" : "Grenzen setzen"}
        </button>
        {saveM.isError && (
          <div className="mt-3">
            <ErrorBox error={saveM.error} />
          </div>
        )}
      </form>
    </section>
  );
}

const MODES: { id: IsolationMode; label: string }[] = [
  { id: "schema", label: "Schema in der gemeinsamen Datenbank" },
  { id: "database", label: "Eigene Datenbank" },
  { id: "cluster", label: "Eigener Cluster" },
];

export function TenantRelocateSection({ tenant }: { tenant: Tenant }) {
  const qc = useQueryClient();
  const [dsnRef, setDsnRef] = useState(tenant.dsn_ref);
  const [mode, setMode] = useState<IsolationMode>(tenant.isolation_mode);
  const [reason, setReason] = useState("");
  // Kein reiner Formular-Schmuck: das ist die eine Vorbedingung, die die API
  // nicht prüfen kann. Sie sieht, dass der Kunde gesperrt ist; ob die Daten im
  // Ziel angekommen sind, weiss nur der Mensch, der den Dump eingespielt hat.
  const [restored, setRestored] = useState(false);

  const suspended = tenant.status === "suspended";

  const moveM = useMutation({
    mutationFn: () => relocateTenant(tenant.id, { dsn_ref: dsnRef, isolation_mode: mode, reason }),
    onSuccess: () => {
      setReason("");
      setRestored(false);
      void qc.invalidateQueries({ queryKey: ["tenant", tenant.id] });
      void qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-2 font-semibold">Ablage umstellen</h2>
      <p className="mb-3 text-xs text-slate-500">
        Das ist der <strong>letzte</strong> Schritt eines Umzugs, nicht der
        Umzug: Sperren, sichern, im Ziel einspielen, prüfen — und dann hier den
        Verweis umstellen und entsperren. Der Ablauf steht in{" "}
        <code className="font-mono">docs/runbooks/betrieb-im-grossen.md</code>.
        Was hinter dem Verweis steckt, hinterlegt die Datenebene in ihrem
        eigenen Geheimnisspeicher; die Konsole erfährt keinen DSN.
      </p>

      {!suspended ? (
        <p className="rounded border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Erst sperren. Ein Umzug bei laufendem Betrieb zeigt die Registry auf
          eine Datenbank, in der die Daten noch nicht vollständig sind — die
          Datenebene bediente den Kunden dann aus einem halb gefüllten Schema.
        </p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            moveM.mutate();
          }}
          className="space-y-3"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">DSN-Verweis</span>
              <input
                required
                pattern="[a-z][a-z0-9_]{1,63}"
                value={dsnRef}
                onChange={(e) => setDsnRef(e.target.value)}
                className="w-full rounded border px-2 py-1 font-mono text-sm"
              />
              <span className="mt-1 block text-xs text-slate-400">
                Daraus wird <code className="font-mono">MAGISTER_TENANT_DSN_</code>
                {dsnRef.toUpperCase() || "…"} auf dem Anwendungsserver.
              </span>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">Trennung</span>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as IsolationMode)}
                className="w-full rounded border px-2 py-1 text-sm"
              >
                {MODES.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Begründung (Pflicht)</span>
            <input
              required
              minLength={5}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Umzug auf eigenen Cluster, Ticket 1234"
              className="w-full rounded border px-2 py-1"
            />
          </label>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={restored}
              onChange={(e) => setRestored(e.target.checked)}
              className="mt-1"
            />
            <span className="text-slate-600">
              Die Sicherung ist im Ziel eingespielt und geprüft.
            </span>
          </label>

          <p className="text-xs text-slate-500">
            Der gemeldete Schemastand wird dabei gelöscht — er war eine Messung
            an der alten Ablage. Die nächste Meldung der Datenebene ist der
            Beleg, dass der Umzug angekommen ist.
          </p>

          <button
            type="submit"
            disabled={moveM.isPending || !restored}
            className="rounded border border-amber-500 px-3 py-1 text-sm text-amber-800 disabled:opacity-50"
          >
            {moveM.isPending ? "Läuft…" : "Verweis umstellen"}
          </button>
          {moveM.isError && (
            <div className="mt-3">
              <ErrorBox error={moveM.error} />
            </div>
          )}
        </form>
      )}
    </section>
  );
}
