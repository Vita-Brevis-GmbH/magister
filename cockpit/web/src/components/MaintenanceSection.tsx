import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelMaintenance,
  listMaintenance,
  requestMaintenance,
  type MaintenanceAction,
} from "../api/operations";
import { StatusBadge } from "./Badge";
import { ErrorBox } from "./ErrorBox";

const ACTIONS: { id: MaintenanceAction; label: string; text: string }[] = [
  {
    id: "demo_purge",
    label: "Demodaten entfernen",
    text: "Entfernt die Demoschule „BSP“ samt Klassen und Zuordnungen. Echte Daten bleiben.",
  },
  {
    id: "audit_reset",
    label: "Aktivitäten zurücksetzen",
    text:
      "Leert das Aktivitätsprotokoll und den Importverlauf — üblich vor der Übergabe. Im " +
      "Protokoll bleibt ein Eintrag, wer es wann und warum geleert hat.",
  },
];

/**
 * Daten und Aktivitäten eines Kunden löschen (ADR-0024 D4).
 *
 * Vorher im Kundenportal. Jetzt hier, als Auftrag: die Installation holt ihn
 * mit dem nächsten Abgleich ab, führt ihn genau einmal aus und meldet das
 * Ergebnis. Im Protokoll des Kunden steht, wer bei Vita Brevis es ausgelöst
 * hat und warum.
 */
export function MaintenanceSection({ tenantId, slug }: { tenantId: string; slug: string }) {
  const qc = useQueryClient();
  const [action, setAction] = useState<MaintenanceAction>("demo_purge");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const listQ = useQuery({
    queryKey: ["maintenance", tenantId],
    queryFn: () => listMaintenance(tenantId),
    retry: false,
    refetchInterval: 20_000,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["maintenance", tenantId] });
  const createM = useMutation({
    mutationFn: () => requestMaintenance(tenantId, { action, reason, confirm_slug: confirm }),
    onSuccess: () => {
      setReason("");
      setConfirm("");
      void invalidate();
    },
  });
  const cancelM = useMutation({
    mutationFn: (id: string) => cancelMaintenance(tenantId, id),
    onSuccess: () => void invalidate(),
  });
  const chosen = ACTIONS.find((a) => a.id === action);

  return (
    <section className="rounded border border-red-200 bg-white p-4">
      <h2 className="mb-2 font-semibold">Daten und Aktivitäten löschen</h2>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          createM.mutate();
        }}
      >
        <div className="flex flex-wrap gap-4 text-sm">
          {ACTIONS.map((a) => (
            <label key={a.id} className="inline-flex items-center gap-1">
              <input
                type="radio"
                name="maintenance-action"
                checked={action === a.id}
                onChange={() => setAction(a.id)}
              />
              {a.label}
            </label>
          ))}
        </div>
        <p className="text-xs text-slate-500">{chosen?.text}</p>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Grund (steht im Protokoll des Kunden)</span>
          <input
            required
            minLength={10}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full rounded border px-2 py-1"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">
            Zur Bestätigung den Kürzel eintippen: <code className="font-mono">{slug}</code>
          </span>
          <input
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="w-48 rounded border px-2 py-1 font-mono"
          />
        </label>
        <button
          type="submit"
          disabled={createM.isPending || confirm !== slug}
          className="rounded border border-red-500 px-3 py-1 text-sm text-red-800 disabled:opacity-50"
        >
          Auftrag erfassen
        </button>
        {createM.isError && <ErrorBox error={createM.error} />}
      </form>

      {listQ.data && listQ.data.length > 0 && (
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-slate-100 text-left">
              <th className="p-2">Erfasst</th>
              <th className="p-2">Auftrag</th>
              <th className="p-2">Zustand</th>
              <th className="p-2">Von</th>
              <th className="p-2">Ergebnis</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {listQ.data.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="p-2 text-xs">{new Date(r.requested_at).toLocaleString()}</td>
                <td className="p-2">{ACTIONS.find((a) => a.id === r.action)?.label ?? r.action}</td>
                <td className="p-2">
                  <StatusBadge status={r.state} />
                </td>
                <td className="p-2 text-xs">{r.requested_by}</td>
                <td className="p-2 font-mono text-xs">
                  {r.result
                    ? Object.entries(r.result)
                        .filter(([k]) => k !== "ok")
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(" ")
                    : r.state === "requested"
                      ? "wartet auf den nächsten Abgleich"
                      : ""}
                </td>
                <td className="p-2">
                  {r.state === "requested" && (
                    <button
                      type="button"
                      onClick={() => cancelM.mutate(r.id)}
                      className="rounded border px-2 py-0.5 text-xs"
                    >
                      Zurückziehen
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
