import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackupWorker } from "../api/backups";
import { getOpsStatus, requestOps } from "../api/platform";
import { StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";

/**
 * Die Plattform als Ganzes (ADR-0024 D5, D6).
 *
 * Neustart und Update betreffen **alle** Kunden auf dem Host. Deshalb stehen
 * sie hier und nicht mehr im Kundenportal, wo der Admin eines Kunden den Host
 * aller Kunden neu starten konnte.
 */
export function Platform() {
  const qc = useQueryClient();
  const opsQ = useQuery({ queryKey: ["platform-ops"], queryFn: getOpsStatus, refetchInterval: 5000 });
  const workerQ = useQuery({ queryKey: ["backup-worker"], queryFn: getBackupWorker, retry: false });
  const opsM = useMutation({
    mutationFn: requestOps,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-ops"] }),
  });

  const ask = (action: "restart" | "update") => {
    const text =
      action === "restart"
        ? "Beide Stacks neu starten? Alle Kunden sind für etwa eine Minute nicht erreichbar."
        : "Update einspielen (git pull, neu bauen, neu starten)? Alle Kunden sind während des Neustarts nicht erreichbar.";
    if (window.confirm(text)) opsM.mutate(action);
  };

  const ops = opsQ.data;
  const last = ops?.last;
  // Gemessen gegen den Zeitpunkt der Antwort, nicht gegen `Date.now()` beim
  // Zeichnen — die Ansicht bleibt damit eine reine Funktion ihrer Daten.
  const workerAge = workerQ.data?.last_seen_at
    ? Math.round(
        (workerQ.dataUpdatedAt - new Date(workerQ.data.last_seen_at).getTime()) / 60000,
      )
    : null;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Plattform</h1>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-2 font-semibold">Neustart und Update</h2>
        {opsQ.isError && <ErrorBox error={opsQ.error} />}
        {ops && !ops.configured && (
          <div className="mb-3 rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
            Nicht eingerichtet. Auf dem Plattform-Host als root:
            <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh ops-agent</pre>
          </div>
        )}
        <div className="mb-3 flex gap-2">
          <button
            type="button"
            disabled={!ops?.configured || opsM.isPending}
            onClick={() => ask("restart")}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            Neu starten
          </button>
          <button
            type="button"
            disabled={!ops?.configured || opsM.isPending}
            onClick={() => ask("update")}
            className="rounded border border-amber-500 px-3 py-1 text-sm text-amber-800 disabled:opacity-50"
          >
            Update einspielen
          </button>
        </div>
        {opsM.isError && <ErrorBox error={opsM.error} />}
        {ops && ops.pending > 0 && (
          <p className="mb-2 text-sm text-slate-600">
            {ops.pending} Auftrag/Aufträge warten auf den Host-Agenten (läuft alle 20 Sekunden).
          </p>
        )}
        {last && (
          <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-slate-500">Letzter Auftrag</dt>
            <dd>
              {last.action}{last.slug ? ` (${last.slug})` : ""} <StatusBadge status={last.state ?? "?"} />
            </dd>
            <dt className="text-slate-500">Bestellt von</dt>
            <dd>{last.requested_by || "—"}</dd>
            <dt className="text-slate-500">Begonnen / beendet</dt>
            <dd>
              {last.started_at ? new Date(last.started_at).toLocaleString() : "—"} /{" "}
              {last.finished_at ? new Date(last.finished_at).toLocaleString() : "läuft"}
            </dd>
            <dt className="text-slate-500">Stand</dt>
            <dd className="font-mono text-xs">{last.git_sha ?? "—"}</dd>
          </dl>
        )}
        {ops?.log && (
          <pre className="mt-3 max-h-80 overflow-auto rounded bg-slate-900 p-2 font-mono text-xs text-slate-100">
            {ops.log}
          </pre>
        )}
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-2 font-semibold">Sicherungen</h2>
        <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-slate-500">Tägliche Sicherung</dt>
          <dd>läuft in der Konsole, Uhrzeit COCKPIT_BACKUP_DAILY_AT (UTC, Vorgabe 01:30)</dd>
          <dt className="text-slate-500">Prüfer</dt>
          <dd className={workerAge === null || workerAge > 15 ? "text-amber-700" : ""}>
            {workerQ.data?.last_seen_at
              ? `zuletzt gemeldet ${new Date(workerQ.data.last_seen_at).toLocaleString()}${
                  workerQ.data.detail ? ` (${workerQ.data.detail})` : ""
                }`
              : "hat sich nie gemeldet — Sicherungen bleiben „written“, bis er läuft"}
          </dd>
        </dl>
        {(workerAge === null || workerAge > 15) && (
          <p className="mt-2 text-xs text-slate-600">
            Einrichten auf dem Host mit dem privaten Backup-Schlüssel (als root):{" "}
            <code className="font-mono">./scripts/plattform-aufbau.sh backup-pruefer</code>
          </p>
        )}
      </section>
    </div>
  );
}
