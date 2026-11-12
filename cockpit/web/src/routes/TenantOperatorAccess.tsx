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

  // Wer zugreift, stand hier als Eingabefeld und ist mit ADR-0020 D3
  // verschwunden: der Name reist signiert mit und landet im Protokoll des
  // Kunden. Selbst eingetippt wäre er eine Behauptung.
  const [reason, setReason] = useState("");
  const [ticket, setTicket] = useState("");
  const [opened, setOpened] = useState<OperatorAccessOpened | null>(null);

  const openM = useMutation({
    mutationFn: () =>
      openOperatorAccess(tenantId, {
        reason,
        ticket: ticket.trim() || null,
      }),
    onSuccess: (out) => {
      setOpened(out);
      setReason("");
      setTicket("");
      return qc.invalidateQueries({ queryKey: ["operator-access", tenantId] });
    },
  });

  return (
    <div className="space-y-6 text-sm">
      <section className="max-w-2xl space-y-3 rounded border bg-slate-50 p-3">
        <h2 className="font-semibold">So funktioniert der Zugriff</h2>
        <p className="text-slate-700">
          Damit sieht Vita Brevis im Support-Fall die Installation des Kunden so, wie ein
          Administrator des Kunden sie sieht („die Klassenlehrerin sieht die Klasse 4a
          nicht“) — ohne Konto im AD des Kunden und ohne Griff in die Datenbank.
        </p>
        <ol className="list-decimal space-y-1 pl-5 text-slate-700">
          <li>
            Grund eintragen (und, wenn vorhanden, die Ticketnummer) und „Zugriff öffnen“.
          </li>
          <li>
            Die Konsole stellt einen signierten <strong>Einlöseschein</strong> aus: 60
            Sekunden gültig, nur einmal verwendbar, nirgends gespeichert.
          </li>
          <li>
            „Installation des Kunden öffnen“ löst ihn ein. Im Portal des Kunden entsteht
            eine Sitzung unter Ihrem Namen, die <strong>eine Stunde</strong> dauert — oder
            bis Sie sich dort abmelden.
          </li>
        </ol>
        <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-slate-700">
          <dt className="text-slate-500">Was Sie dürfen</dt>
          <dd>
            Alles <strong>lesen</strong>, an allen Standorten, wie ein Admin des Kunden.
          </dd>
          <dt className="text-slate-500">Was nicht geht</dt>
          <dd>
            Nichts ändern: jede schreibende Aktion wird abgewiesen, auch Passwort-Resets.
            Die Passwortliste einer Klasse bleibt zu. Für Änderungen: der Kunde selbst,
            oder das lokale Administrationskonto unter „Einstellungen“.
          </dd>
          <dt className="text-slate-500">Was der Kunde sieht</dt>
          <dd>
            Solange die Sitzung läuft, einen Hinweisbalken bei <strong>jedem</strong>{" "}
            angemeldeten Benutzer. Danach in seiner Zugriffsliste und im Protokoll: wer,
            wann, wie lange und warum — der Grund steht dort wörtlich.
          </dd>
          <dt className="text-slate-500">Was nicht entsteht</dt>
          <dd>
            Kein Benutzer, keine Rolle, kein Eintrag im AD des Kunden. Nach Ablauf bleibt
            nur der Protokolleintrag.
          </dd>
        </dl>
      </section>

      <section className="max-w-2xl space-y-3">

        {openM.isError && <ErrorBox error={openM.error} />}

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
          disabled={openM.isPending || reason.trim().length < 10}
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
