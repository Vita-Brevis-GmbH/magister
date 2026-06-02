import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { listInstances, pollInstance } from "./api";

export function App() {
  const [tokenInput, setTokenInput] = useState(localStorage.getItem("cockpit_token") ?? "");
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["instances"], queryFn: listInstances, retry: false });
  const m = useMutation({
    mutationFn: pollInstance,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instances"] }),
  });

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
              qc.invalidateQueries({ queryKey: ["instances"] });
            }}
            className="rounded bg-slate-900 px-3 py-1 text-sm text-white"
          >
            Auth setzen
          </button>
        </div>
      </header>

      {q.isLoading && <p>Lade…</p>}
      {q.isError && <p className="text-red-600">Fehler: {String(q.error)}</p>}
      {q.data && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-slate-100 text-left">
              <th className="p-2">Schulträger</th>
              <th className="p-2">URL</th>
              <th className="p-2">Channel</th>
              <th className="p-2">Version</th>
              <th className="p-2">Health</th>
              <th className="p-2">Letzter Check</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((i) => (
              <tr key={i.id} className="border-b">
                <td className="p-2 font-medium">
                  {i.display_name} <span className="text-slate-500">({i.slug})</span>
                </td>
                <td className="p-2 font-mono text-xs">{i.base_url}</td>
                <td className="p-2">{i.channel}</td>
                <td className="p-2 font-mono">{i.deployed_version ?? "—"}</td>
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
                  {i.last_health_at ? new Date(i.last_health_at).toLocaleString() : "—"}
                </td>
                <td className="p-2">
                  <button
                    onClick={() => m.mutate(i.id)}
                    className="rounded border px-2 py-1 text-xs"
                  >
                    Poll
                  </button>
                </td>
              </tr>
            ))}
            {q.data.length === 0 && (
              <tr>
                <td colSpan={7} className="p-4 text-center text-slate-500">
                  Keine Instanzen erfasst.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
