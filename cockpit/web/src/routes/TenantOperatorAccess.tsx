import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  listOperatorAccess,
  openOperatorAccess,
  type OperatorAccessOpened,
} from "../api/operatorAccess";
import { ErrorBox } from "../components/ErrorBox";

/**
 * Einen Zugriff auf die Installation des Kunden öffnen (ADR-0019).
 *
 * Was hier entsteht, ist **kein** Zugang, sondern ein Einlöseschein: sechzig
 * Sekunden gültig, einmal verwendbar. Er wird einmal angezeigt und nirgends
 * gespeichert — deshalb steht er hier so, dass man ihn nicht versehentlich
 * wegklickt.
 *
 * Der Grund ist Pflicht und reist signiert mit: er landet unverändert im
 * Protokoll des Kunden und im Balken, den dessen Benutzer sehen.
 */
export function TenantOperatorAccess({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const historyQ = useQuery({
    queryKey: ["operator-access", tenantId],
    queryFn: () => listOperatorAccess(tenantId),
    retry: false,
  });

  const [operator, setOperator] = useState(
    () => sessionStorage.getItem("cockpit_actor") ?? "",
  );
  const [reason, setReason] = useState("");
  const [ticket, setTicket] = useState("");
  const [opened, setOpened] = useState<OperatorAccessOpened | null>(null);

  const openM = useMutation({
    mutationFn: () =>
      openOperatorAccess(tenantId, {
        operator,
        reason,
        ticket: ticket.trim() || null,
      }),
    onSuccess: (out) => {
      sessionStorage.setItem("cockpit_actor", operator);
      setOpened(out);
      setReason("");
      setTicket("");
      return qc.invalidateQueries({ queryKey: ["operator-access", tenantId] });
    },
  });

  return (
    <div className="space-y-6 text-sm">
      <section className="max-w-2xl space-y-3">
        <p className="text-slate-600">
          Ein Zugriff ist <strong>lesend</strong>, auf eine Stunde befristet und für den
          Kunden sichtbar: seine Benutzer sehen einen Hinweisbalken, solange er läuft, und
          der Grund steht in ihrem Protokoll. Ändern kann ein Zugriff nichts — auch die
          Passwortliste einer Klasse bleibt zu.
        </p>

        {openM.isError && <ErrorBox error={openM.error} />}

        <label className="block">
          <span className="mb-1 block text-slate-600">Wer greift zu</span>
          <input
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="vorname.nachname@vitabrevis.ch"
            className="w-full rounded border px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">
            Grund (steht im Protokoll des Kunden, mindestens 10 Zeichen)
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full rounded border p-2"
            placeholder="Ticket 4711: Klassenlehrerin sieht die Klasse 4a nicht."
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Ticketnummer (optional)</span>
          <input
            value={ticket}
            onChange={(e) => setTicket(e.target.value)}
            className="w-full rounded border px-2 py-1"
          />
        </label>

        <button
          type="button"
          onClick={() => openM.mutate()}
          disabled={openM.isPending || reason.trim().length < 10 || !operator.trim()}
          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
        >
          {openM.isPending ? "Stelle aus…" : "Zugriff öffnen"}
        </button>
      </section>

      {opened && (
        <section className="max-w-2xl space-y-2 rounded border border-amber-400 bg-amber-50 p-3">
          <p className="font-medium text-amber-900">
            Einlöseschein ausgestellt — gültig bis{" "}
            {new Date(opened.expires_at).toLocaleTimeString("de-CH")}
          </p>
          <p className="text-amber-900">
            Er gilt <strong>sechzig Sekunden</strong> und lässt sich <strong>einmal</strong>{" "}
            einlösen. Jetzt öffnen; danach einen neuen ausstellen.
          </p>
          {/*
            `rel="noreferrer"` ist hier nicht Gewohnheit: der Schein steht im
            Fragment, und ein Fragment gehört nicht in einen Referer — auch
            wenn Browser es heute ohnehin weglassen.
          */}
          <a
            href={opened.redeem_url}
            target="_blank"
            rel="noreferrer"
            className="inline-block rounded bg-slate-900 px-3 py-1 text-white"
          >
            Installation des Kunden öffnen
          </a>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-slate-600">Ausgestellt</h2>
        {historyQ.isError && <ErrorBox error={historyQ.error} />}
        {historyQ.data?.length === 0 && (
          <p className="text-slate-500">Für diesen Kunden wurde noch kein Zugriff geöffnet.</p>
        )}
        {historyQ.data && historyQ.data.length > 0 && (
          <table className="w-full border-collapse">
            <thead className="border-b text-left text-slate-600">
              <tr>
                <th className="py-1 pr-3 font-medium">Ausgestellt</th>
                <th className="py-1 pr-3 font-medium">Wer</th>
                <th className="py-1 pr-3 font-medium">Grund</th>
              </tr>
            </thead>
            <tbody>
              {historyQ.data.map((row) => (
                <tr key={row.jti} className="border-b last:border-0">
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {new Date(row.issued_at).toLocaleString("de-CH")}
                  </td>
                  <td className="py-1 pr-3">{row.operator}</td>
                  <td className="py-1 pr-3">
                    {row.ticket && (
                      <span className="mr-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                        {row.ticket}
                      </span>
                    )}
                    {row.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-2 max-w-2xl text-xs text-slate-500">
          Diese Liste zeigt, was die Konsole <em>ausgestellt</em> hat. Ob ein Schein
          eingelöst wurde, steht im Protokoll des Kunden — die Konsole hat zu dessen Schema
          keinen Zugang, und das ist der Grund, aus dem ein Einbruch hier nicht auch einer
          bei jedem Kunden ist.
        </p>
      </section>
    </div>
  );
}
