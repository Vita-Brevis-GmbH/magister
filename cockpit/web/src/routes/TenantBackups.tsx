import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createBackup,
  downloadExport,
  getBackupPolicy,
  listBackups,
  listExports,
  listRestoreJobs,
  requestExport,
  updateBackupPolicy,
  type Backup,
  type BackupPolicy,
} from "../api/backups";
import { StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";

function bytes(value: number | null): string {
  if (value === null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * `asOf` statt `Date.now()`: ESLint hat den ersten Entwurf zu Recht
 * beanstandet („Cannot call impure function during render"). Der bessere Wert
 * ist ohnehin nicht „jetzt", sondern der Zeitpunkt, zu dem diese Daten geholt
 * wurden — react-query nennt ihn `dataUpdatedAt`. Damit werden alle Zeilen
 * gegen denselben Augenblick beurteilt, und die Anzeige ändert sich nicht
 * zwischen zwei Neuzeichnungen ohne neue Daten.
 */
function BackupRow({ backup, asOf }: { backup: Backup; asOf: number }) {
  const stale =
    backup.status === "written" && asOf - new Date(backup.started_at).getTime() > 8 * 86_400_000;
  return (
    <tr className="border-b">
      <td className="p-2 text-xs">{new Date(backup.started_at).toLocaleString()}</td>
      <td className="p-2">
        <StatusBadge status={backup.kind} />
      </td>
      <td className="p-2">
        <StatusBadge status={backup.status} />
        {stale && (
          <span className="ml-2 text-xs text-amber-700" title="verified_at älter als 8 Tage">
            ungeprüft
          </span>
        )}
      </td>
      <td className="p-2 text-right text-xs">{bytes(backup.size_bytes)}</td>
      <td className="p-2 font-mono text-xs">{backup.schema_version ?? "—"}</td>
      <td className="p-2 font-mono text-xs">{backup.audit_key_id ?? "—"}</td>
      <td className="p-2 text-xs">
        {backup.verified_at ? new Date(backup.verified_at).toLocaleDateString() : "—"}
      </td>
      <td className="p-2 text-xs text-red-700">{backup.error ?? backup.verify_detail ?? ""}</td>
    </tr>
  );
}

function PolicyForm({ tenantId, policy }: { tenantId: string; policy: BackupPolicy }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(policy);
  const saveM = useMutation({
    mutationFn: () =>
      updateBackupPolicy(tenantId, {
        retention_days: draft.retention_days,
        pre_migration_retention_days: draft.pre_migration_retention_days,
        monthly_enabled: draft.monthly_enabled,
        monthly_keep: draft.monthly_keep,
        rpo_hours: draft.rpo_hours,
        rto_hours: draft.rto_hours,
        share_root: draft.share_root,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backup-policy", tenantId] }),
  });

  const num = (key: keyof BackupPolicy, label: string, hint?: string) => (
    <label className="block">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        type="number"
        min={1}
        value={String(draft[key] ?? "")}
        onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
        className="w-24 rounded border px-2 py-1 text-right"
      />
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );

  return (
    <form
      className="rounded border bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        saveM.mutate();
      }}
    >
      <h2 className="mb-3 font-semibold">Aufbewahrung</h2>
      <div className="mb-3 grid grid-cols-3 gap-4 text-sm">
        {num("retention_days", "Tage", "Tägliche Sicherungen (Vorgabe 10).")}
        {num("pre_migration_retention_days", "Tage vor Migration")}
        {num("monthly_keep", "Monatskopien behalten", "Zwölf heisst: ein Jahr zurück.")}
        {num("rpo_hours", "RPO (Stunden)")}
        {num("rto_hours", "RTO (Stunden)")}
        <label className="block">
          <span className="mb-1 block text-slate-600">Monatskopien schreiben</span>
          <input
            type="checkbox"
            checked={draft.monthly_enabled}
            onChange={(e) => setDraft({ ...draft, monthly_enabled: e.target.checked })}
            className="mr-2"
          />
          <span className="text-xs text-slate-600">
            Die erste geglückte Sicherung eines Monats wird <em>als</em> Monatskopie
            geschrieben — kein zweiter Dump.
          </span>
        </label>
      </div>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-slate-600">Share</span>
        <input
          value={draft.share_root ?? ""}
          onChange={(e) => setDraft({ ...draft, share_root: e.target.value })}
          placeholder="/mnt/magister-backup"
          className="w-full rounded border px-2 py-1 font-mono text-xs"
        />
      </label>
      {saveM.isError && <ErrorBox error={saveM.error} />}
      <button
        type="submit"
        disabled={saveM.isPending}
        className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {saveM.isPending ? "Speichert…" : "Speichern"}
      </button>
      <span className="ml-3 text-xs text-slate-500">
        Zuletzt geändert {new Date(policy.updated_at).toLocaleString()}
      </span>
    </form>
  );
}

export function TenantBackups({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [exportBy, setExportBy] = useState("");

  const backupsQ = useQuery({
    queryKey: ["backups", tenantId],
    queryFn: () => listBackups(tenantId),
    retry: false,
    refetchInterval: 20_000,
  });
  const policyQ = useQuery({
    queryKey: ["backup-policy", tenantId],
    queryFn: () => getBackupPolicy(tenantId),
    retry: false,
  });
  const restoreQ = useQuery({
    queryKey: ["restore-jobs", tenantId],
    queryFn: () => listRestoreJobs(tenantId),
    retry: false,
  });
  const exportsQ = useQuery({
    queryKey: ["exports", tenantId],
    queryFn: () => listExports(tenantId),
    retry: false,
  });

  const manualM = useMutation({
    mutationFn: () => createBackup(tenantId, "manual"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups", tenantId] }),
  });
  const exportM = useMutation({
    mutationFn: () => requestExport(tenantId, exportBy),
    onSuccess: () => {
      setExportBy("");
      void qc.invalidateQueries({ queryKey: ["exports", tenantId] });
    },
  });
  const downloadM = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => downloadExport(id, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exports", tenantId] }),
  });

  return (
    <div className="space-y-6">
      <section className="rounded border bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Sicherungen</h2>
          <button
            type="button"
            onClick={() => manualM.mutate()}
            disabled={manualM.isPending}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            {manualM.isPending ? "Läuft…" : "Sicherung jetzt"}
          </button>
        </div>
        {manualM.isError && <ErrorBox error={manualM.error} />}
        {backupsQ.isError && <ErrorBox error={backupsQ.error} />}
        {backupsQ.data && (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Begonnen</th>
                <th className="p-2">Art</th>
                <th className="p-2">Zustand</th>
                <th className="p-2 text-right">Grösse</th>
                <th className="p-2">Schema</th>
                <th className="p-2">Schlüssel-Id</th>
                <th className="p-2">Geprüft</th>
                <th className="p-2">Befund</th>
              </tr>
            </thead>
            <tbody>
              {backupsQ.data.map((b) => (
                <BackupRow key={b.id} backup={b} asOf={backupsQ.dataUpdatedAt} />
              ))}
              {backupsQ.data.length === 0 && (
                <tr>
                  <td colSpan={8} className="p-4 text-center text-slate-500">
                    Noch keine Sicherung.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
        <p className="mt-2 text-xs text-slate-500">
          Die Prüf-Wiederherstellung läuft auf dem Backup-Host — dort liegt der private
          Schlüssel. Diese Ansicht <em>erfasst</em> Aufträge und <em>nimmt Ergebnisse
          entgegen</em>; sie führt nichts aus.
        </p>
      </section>

      {policyQ.data && <PolicyForm tenantId={tenantId} policy={policyQ.data} />}
      {policyQ.isError && <ErrorBox error={policyQ.error} />}

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Wiederherstellungen</h2>
        {restoreQ.data && restoreQ.data.length > 0 ? (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Erfasst</th>
                <th className="p-2">Zustand</th>
                <th className="p-2">Zielschema</th>
                <th className="p-2">Grund</th>
                <th className="p-2">Angefragt von</th>
                <th className="p-2">Freigegeben von</th>
              </tr>
            </thead>
            <tbody>
              {restoreQ.data.map((j) => (
                <tr key={j.id} className="border-b">
                  <td className="p-2 text-xs">{new Date(j.created_at).toLocaleString()}</td>
                  <td className="p-2">
                    <StatusBadge status={j.state} />
                  </td>
                  <td className="p-2 font-mono text-xs">{j.target_schema}</td>
                  <td className="p-2 text-xs">{j.reason}</td>
                  <td className="p-2 text-xs">{j.requested_by}</td>
                  <td className="p-2 text-xs">{j.approved_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-slate-500">Keine Wiederherstellung erfasst.</p>
        )}
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Exporte</h2>
        <form
          className="mb-3 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            exportM.mutate();
          }}
        >
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Bestellt von</span>
            <input
              required
              value={exportBy}
              onChange={(e) => setExportBy(e.target.value)}
              placeholder="matthias.hadorn@vitabrevis.ch"
              className="w-72 rounded border px-2 py-1"
            />
          </label>
          <button
            type="submit"
            disabled={exportM.isPending}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            Export bestellen
          </button>
        </form>
        {exportM.isError && <ErrorBox error={exportM.error} />}
        {downloadM.isError && <ErrorBox error={downloadM.error} />}
        {exportsQ.data && exportsQ.data.length > 0 ? (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Bestellt</th>
                <th className="p-2">Zustand</th>
                <th className="p-2 text-right">Grösse</th>
                <th className="p-2">Gültig bis</th>
                <th className="p-2">Von</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {exportsQ.data.map((x) => (
                <tr key={x.id} className="border-b">
                  <td className="p-2 text-xs">{new Date(x.created_at).toLocaleString()}</td>
                  <td className="p-2">
                    <StatusBadge status={x.state} />
                  </td>
                  <td className="p-2 text-right text-xs">{bytes(x.size_bytes)}</td>
                  <td className="p-2 text-xs">
                    {x.expires_at ? new Date(x.expires_at).toLocaleString() : "—"}
                  </td>
                  <td className="p-2 text-xs">{x.requested_by}</td>
                  <td className="p-2">
                    {(x.state === "ready" || x.state === "downloaded") && (
                      <button
                        type="button"
                        onClick={() =>
                          downloadM.mutate({
                            id: x.id,
                            name: x.path?.split("/").pop() ?? `export-${x.id}.zip`,
                          })
                        }
                        disabled={downloadM.isPending}
                        className="rounded border px-2 py-1 text-xs disabled:opacity-50"
                      >
                        Herunterladen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-slate-500">Kein Export bestellt.</p>
        )}
        <p className="mt-2 text-xs text-slate-500">
          Ein Export ist der einzige Ort mit Kundendaten im Klartext. Er hat deshalb eine
          Frist, und jeder Download steht im Protokoll.
        </p>
      </section>
    </div>
  );
}
