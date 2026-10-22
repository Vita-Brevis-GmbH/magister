import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getOpsStatus, requestAttach, requestRotateRole } from "../api/platform";
import { ErrorBox } from "./ErrorBox";

const ACTION_LABEL: Record<string, string> = {
  attach: "Anbinden",
  "rotate-role": "Rollenpasswort neu",
};

const STATE_LABEL: Record<string, string> = {
  running: "läuft",
  success: "erledigt",
  error: "gescheitert",
};

/**
 * Den Kunden auf der Datenebene anbinden (ADR-0024, Nachtrag 2026-10-07).
 *
 * Die Konsole gibt Rollenpasswort und Kundenschlüssel beim Anlegen genau
 * einmal aus und speichert beides nicht. Ein in der Oberfläche angelegter
 * Kunde blieb deshalb auf der Datenebene unbekannt, und sein Portal
 * antwortete mit 503. Dieser Knopf bestellt beim Host-Agenten, was fehlt:
 * DSN (mit neu gesetztem Rollenpasswort) und, solange das Schema noch kein
 * Chiffrat enthält, einen neuen Kundenschlüssel. Schema und Daten bleiben.
 *
 * Daneben „Rollenpasswort neu setzen": derselbe Agent dreht das Passwort und
 * schreibt den DSN im selben Lauf. Vorher drehte die Konsole es direkt und
 * zeigte es einmal an — die Datenebene behielt den alten DSN, und jede neue
 * Datenbankverbindung des Kunden schlug fehl (Prod, 2026-10-16).
 */
export function AttachToDataPlane({ tenantId, slug }: { tenantId: string; slug: string }) {
  const qc = useQueryClient();
  const opsQ = useQuery({
    queryKey: ["platform-ops"],
    queryFn: getOpsStatus,
    refetchInterval: (query) => {
      const data = query.state.data;
      const busy = (data?.pending ?? 0) > 0 || data?.last?.state === "running";
      return busy ? 5000 : 60_000;
    },
  });
  const m = useMutation({
    mutationFn: () => requestAttach(tenantId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-ops"] }),
  });
  const rotateM = useMutation({
    mutationFn: () => requestRotateRole(tenantId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-ops"] }),
  });

  const ops = opsQ.data;
  const last =
    ops?.last && ops.last.slug === slug && (ops.last.action ?? "") in ACTION_LABEL
      ? ops.last
      : null;
  const busy = m.isPending || rotateM.isPending || last?.state === "running";

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-2 font-semibold">Anbindung an die Datenebene</h2>
      <p className="mb-3 text-sm text-slate-600">
        Trägt auf dem Anwendungsserver nach, was der Datenebene für diesen Kunden fehlt:
        Datenbankzugang und Kundenschlüssel. Nötig, wenn das Portal mit 503 antwortet oder die
        Installation sich nie meldet. Schema und Daten bleiben unberührt. Fehlt der
        Datenbankzugang, wird das Rollenpasswort neu gesetzt.
      </p>
      {opsQ.isError && <ErrorBox error={opsQ.error} />}
      {ops && !ops.configured && (
        <div className="mb-3 rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          Der Host-Agent ist nicht eingerichtet. Auf dem Plattform-Host als root:
          <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh ops-agent</pre>
          oder direkt:
          <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh kunde-anbinden {slug}</pre>
          bzw. für ein neues Rollenpasswort:
          <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh rollenpasswort-neu {slug}</pre>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!ops?.configured || busy}
          onClick={() => {
            if (
              window.confirm(
                `Kunde „${slug}" auf der Datenebene anbinden? Fehlt dort der Datenbankzugang, ` +
                  "wird das Rollenpasswort neu gesetzt und die Datenebene neu gestartet.",
              )
            ) {
              m.mutate();
            }
          }}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          Auf der Datenebene anbinden
        </button>
        <button
          type="button"
          disabled={!ops?.configured || busy}
          onClick={() => {
            if (
              window.confirm(
                `Für „${slug}" ein neues Rollenpasswort setzen? Der Host-Agent trägt es ` +
                  "selbst in den Datenbankzugang der Datenebene ein und startet sie neu " +
                  "(alle Kunden sind dabei einige Sekunden nicht erreichbar).",
              )
            ) {
              rotateM.mutate();
            }
          }}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          Rollenpasswort neu setzen
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Das neue Passwort entsteht auf dem Host und wird nirgends angezeigt — es muss nicht in
        den Passwortspeicher. Nötig bei Verdacht auf Abfluss oder wenn das Portal-Log
        „password authentication failed“ meldet.
      </p>
      {m.isError && <ErrorBox error={m.error} />}
      {rotateM.isError && <ErrorBox error={rotateM.error} />}
      {(m.isSuccess || rotateM.isSuccess) && !last && (
        <p className="mt-2 text-sm text-slate-600">
          Bestellt. Der Host-Agent holt den Auftrag innerhalb von 20 Sekunden ab.
        </p>
      )}
      {last && (
        <div className="mt-3 text-sm">
          <p
            className={
              last.state === "success"
                ? "text-emerald-700"
                : last.state === "error"
                  ? "text-red-700"
                  : "text-slate-700"
            }
          >
            Zuletzt „{ACTION_LABEL[last.action ?? ""]}“:{" "}
            {STATE_LABEL[last.state ?? ""] ?? last.state}
            {last.finished_at ? ` · ${new Date(last.finished_at).toLocaleString()}` : ""}
            {last.requested_by ? ` · von ${last.requested_by}` : ""}
          </p>
          {last.message && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-50 p-2 font-mono text-xs">
              {last.message}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
