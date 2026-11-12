import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  getTenantStatus,
  listMaintenance,
  orderPlatformMailTest,
  orderTenantMailTest,
  type MailTestOrder,
} from "../api/operations";
import { ErrorBox } from "./ErrorBox";

/** Wie lange auf das Ergebnis gewartet wird, bevor die Box aufgibt. */
const WAIT_MS = 3 * 60_000;

/**
 * Echte Testmail mit frei wählbarem Empfänger.
 *
 * Die Konsole kann selbst nicht senden — sie kennt das versiegelte Geheimnis
 * nicht. Sie erfasst einen Auftrag; die Installation des Kunden sendet beim
 * nächsten Abgleich (meist innerhalb einer Minute) mit der Anbindung, die
 * dann für sie gilt, und meldet das Ergebnis zurück. Die Box fragt so lange
 * nach.
 *
 * Ohne ``tenantId``: Testmail mit dem Plattform-Standard, über einen Kunden,
 * der ihn verwendet.
 */
export function MailTestBox({ tenantId }: { tenantId?: string }) {
  const [to, setTo] = useState("");
  const [order, setOrder] = useState<MailTestOrder | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const orderM = useMutation({
    mutationFn: () =>
      tenantId ? orderTenantMailTest(tenantId, to.trim()) : orderPlatformMailTest(to.trim()),
    onSuccess: (data) => {
      setOrder(data);
      setStartedAt(Date.now());
    },
  });
  const resultQ = useQuery({
    queryKey: ["mail-test", order?.request.id],
    queryFn: async () => {
      const rows = await listMaintenance(order!.tenant_id);
      return rows.find((r) => r.id === order!.request.id) ?? null;
    },
    enabled: order !== null,
    refetchInterval: (q) => {
      const state = q.state.data?.state;
      if (state && state !== "requested") return false;
      return Date.now() - startedAt < WAIT_MS ? 3000 : false;
    },
  });
  // Solange gewartet wird: was die Installation zuletzt gemeldet hat. Steht
  // dort ein gescheiterter Abgleich, kommt der Auftrag nie an — und genau das
  // soll hier sichtbar sein statt eines endlosen „wartet …".
  const waitingForResult = order !== null && (!resultQ.data || resultQ.data.state === "requested");
  const statusQ = useQuery({
    queryKey: ["tenant-status", order?.tenant_id],
    queryFn: () => getTenantStatus(order!.tenant_id),
    enabled: waitingForResult,
    refetchInterval: waitingForResult ? 5000 : false,
  });
  const row = resultQ.data;
  const waiting = order !== null && (!row || row.state === "requested");
  // Gemessen am Zeitpunkt der letzten Antwort, nicht an `Date.now()` beim
  // Zeichnen — die Ansicht bleibt eine Funktion ihrer Daten.
  const timedOut = waiting && resultQ.dataUpdatedAt - startedAt >= WAIT_MS;
  const error = row?.result && typeof row.result.error === "string" ? row.result.error : null;

  return (
    <div className="space-y-2">
      <span className="block text-sm text-slate-600">Testmail</span>
      <div className="flex flex-wrap gap-2">
        <input
          type="email"
          value={to}
          onChange={(e) => {
            setTo(e.target.value);
            setOrder(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (to.trim() && !orderM.isPending) orderM.mutate();
            }
          }}
          placeholder="empfaenger@beispiel.ch"
          aria-label="Testmail an"
          className="w-80 rounded border px-2 py-1 text-sm"
        />
        <button
          type="button"
          onClick={() => orderM.mutate()}
          disabled={!to.trim() || orderM.isPending || (waiting && !timedOut)}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          Testmail senden
        </button>
      </div>
      {orderM.isError && <ErrorBox error={orderM.error} />}
      {order && waiting && statusQ.data && (
        <TenantPulse status={statusQ.data} slug={order.tenant_slug} since={startedAt} />
      )}
      {order && (
        <p
          role="status"
          className={`text-sm ${
            row?.state === "done"
              ? "text-emerald-700"
              : row?.state === "failed" || timedOut
                ? "text-red-700"
                : "text-slate-600"
          }`}
        >
          {row?.state === "done"
            ? `Gesendet an ${to.trim()} (über ${order.tenant_slug}). Bitte im Postfach prüfen.`
            : row?.state === "failed"
              ? `Nicht gesendet (über ${order.tenant_slug}): ${error ?? "unbekannter Fehler"}`
              : row?.state === "cancelled"
                ? "Durch einen neueren Testauftrag ersetzt."
                : timedOut
                  ? `Keine Antwort von ${order.tenant_slug} nach drei Minuten — läuft der Abgleich?`
                  : `Auftrag an ${order.tenant_slug} übergeben — wartet auf den nächsten Abgleich …`}
        </p>
      )}
    </div>
  );
}

/** Letzte Meldung der Installation: wann, und ob ihr Abgleich gelingt. */
function TenantPulse({
  status,
  slug,
  since,
}: {
  status: Awaited<ReturnType<typeof getTenantStatus>>;
  slug: string;
  since: number;
}) {
  const reported = status.reported_at ? new Date(status.reported_at) : null;
  const reconcile = status.report?.reconcile;
  const fresh = reported !== null && reported.getTime() >= since;
  return (
    <p className="text-xs text-slate-500">
      Letzte Meldung von {slug}:{" "}
      {reported ? reported.toLocaleTimeString("de-CH") : "noch nie"}
      {fresh ? " (nach dem Auftrag)" : " (vor dem Auftrag)"}
      {reconcile &&
        (reconcile.ok ? (
          " — Abgleich gelingt."
        ) : (
          <span className="text-red-700">
            {" "}
            — Abgleich scheitert: {reconcile.error ?? "ohne Angabe"}
          </span>
        ))}
    </p>
  );
}
