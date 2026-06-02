import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelUpdateRequest,
  listInstances,
  listUpdateRequests,
  pollInstance,
  requestUpdate,
  type Instance,
  type UpdateRequest,
} from "./api";

function hasUpdate(i: Instance): boolean {
  return (
    i.latest_available_version !== null &&
    i.deployed_version !== null &&
    i.latest_available_version !== i.deployed_version
  );
}

export function App() {
  const [tokenInput, setTokenInput] = useState(localStorage.getItem("cockpit_token") ?? "");
  const qc = useQueryClient();
  const instancesQ = useQuery({
    queryKey: ["instances"],
    queryFn: listInstances,
    retry: false,
    refetchInterval: 30_000,
  });
  const requestsQ = useQuery({
    queryKey: ["update-requests"],
    queryFn: () => listUpdateRequests(),
    retry: false,
    refetchInterval: 30_000,
  });
  const pollM = useMutation({
    mutationFn: pollInstance,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instances"] }),
  });
  const requestM = useMutation({
    mutationFn: (id: string) => requestUpdate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["update-requests"] }),
  });
  const cancelM = useMutation({
    mutationFn: cancelUpdateRequest,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["update-requests"] }),
  });

  const pendingForInstance = (id: string): UpdateRequest | undefined =>
    requestsQ.data?.find((r) => r.instance_id === id && r.status === "pending");

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Vita Brevis Cockpit</h1>
        <div className="flex gap-2">
          <input
            type="password"
            placeholder="Bootstrap-Token"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          />
          <button
            onClick={() => {
              localStorage.setItem("cockpit_token", tokenInput);
              qc.invalidateQueries();
            }}
            className="rounded bg-slate-900 px-3 py-1 text-sm text-white"
          >
            Auth setzen
          </button>
        </div>
      </header>

      {instancesQ.isLoading && <p>Lade…</p>}
      {instancesQ.isError && (
        <p className="text-red-600">Fehler: {String(instancesQ.error)}</p>
      )}
      {instancesQ.data && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-slate-100 text-left">
              <th className="p-2">Schulträger</th>
              <th className="p-2">URL</th>
              <th className="p-2">Channel</th>
              <th className="p-2">Deployed</th>
              <th className="p-2">Available</th>
              <th className="p-2">Health</th>
              <th className="p-2">Letzter Check</th>
              <th className="p-2">Aktion</th>
            </tr>
          </thead>
          <tbody>
            {instancesQ.data.map((i) => {
              const updateAvailable = hasUpdate(i);
              const pending = pendingForInstance(i.id);
              return (
                <tr key={i.id} className="border-b">
                  <td className="p-2 font-medium">
                    {i.display_name} <span className="text-slate-500">({i.slug})</span>
                  </td>
                  <td className="p-2 font-mono text-xs">{i.base_url}</td>
                  <td className="p-2">{i.channel}</td>
                  <td className="p-2 font-mono">{i.deployed_version ?? "—"}</td>
                  <td className="p-2 font-mono">
                    {i.latest_available_version ?? "—"}
                    {updateAvailable && (
                      <span className="ml-2 rounded bg-amber-200 px-1.5 py-0.5 text-xs text-amber-900">
                        Update verfügbar
                      </span>
                    )}
                  </td>
                  <td className="p-2">
                    <span
                      className={
                        i.last_health_status === "ok"
                          ? "text-green-700"
                          : i.last_health_status
                            ? "text-red-700"
                            : "text-slate-500"
                      }
                    >
                      {i.last_health_status ?? "—"}
                    </span>
                  </td>
                  <td className="p-2 text-xs text-slate-500">
                    {i.last_health_at
                      ? new Date(i.last_health_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="p-2 space-x-1">
                    <button
                      onClick={() => pollM.mutate(i.id)}
                      className="rounded border px-2 py-1 text-xs"
                    >
                      Poll
                    </button>
                    {pending ? (
                      <button
                        onClick={() => cancelM.mutate(pending.id)}
                        className="rounded border border-slate-400 px-2 py-1 text-xs"
                        title={`pending → ${pending.target_version}`}
                      >
                        Abbrechen
                      </button>
                    ) : (
                      updateAvailable && (
                        <button
                          onClick={() => requestM.mutate(i.id)}
                          className="rounded bg-amber-500 px-2 py-1 text-xs text-white"
                        >
                          Update einplanen
                        </button>
                      )
                    )}
                  </td>
                </tr>
              );
            })}
            {instancesQ.data.length === 0 && (
              <tr>
                <td colSpan={8} className="p-4 text-center text-slate-500">
                  Keine Instanzen erfasst.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {requestsQ.data && requestsQ.data.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-2 text-lg font-semibold">Update-Anfragen</h2>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Angefragt</th>
                <th className="p-2">Instanz</th>
                <th className="p-2">Ziel-Version</th>
                <th className="p-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {requestsQ.data.slice(0, 50).map((r) => {
                const inst = instancesQ.data?.find((i) => i.id === r.instance_id);
                return (
                  <tr key={r.id} className="border-b">
                    <td className="p-2 text-xs">
                      {new Date(r.requested_at).toLocaleString()}
                    </td>
                    <td className="p-2">{inst?.slug ?? r.instance_id.slice(0, 8)}</td>
                    <td className="p-2 font-mono">{r.target_version}</td>
                    <td className="p-2">{r.status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
