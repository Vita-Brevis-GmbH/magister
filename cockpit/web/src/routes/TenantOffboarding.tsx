import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { listExports } from "../api/backups";
import {
  abortOffboarding,
  confirmKeyDestroyed,
  dropTenantData,
  getOffboarding,
  markPurged,
  recordExportDelivered,
  startOffboarding,
  type Offboarding,
} from "../api/offboarding";
import { StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";

/** Was in diesem Zustand als nächstes dran ist, und was es kostet. */
const STEPS: { state: Offboarding["state"]; title: string; note: string }[] = [
  {
    state: "requested",
    title: "1 · Erfasst",
    note: "Der Kunde wird ab sofort nicht mehr bedient (503). Die Daten stehen unverändert.",
  },
  {
    state: "export_ready",
    title: "2 · Export zugestellt",
    note: "Hieran hängt die Löschsperre: vorher weigert sich Schritt 3.",
  },
  {
    state: "dropped",
    title: "3 · Schema und Rolle gelöscht",
    note: "Unwiderruflich, und deshalb von zwei verschiedenen Personen.",
  },
  {
    state: "shredded",
    title: "4 · Kundenschlüssel vernichtet",
    note: "Damit sind auch die Sicherungen unlesbar — Crypto-Shredding.",
  },
  {
    state: "purged",
    title: "5 · Aufbewahrungsfrist abgelaufen",
    note: "Die Dumps auf dem Share sind weg.",
  },
];

function Timeline({ offboarding }: { offboarding: Offboarding }) {
  const done = new Set<string>();
  const order = STEPS.map((s) => s.state);
  const reached = order.indexOf(offboarding.state);
  order.slice(0, reached + 1).forEach((s) => done.add(s));

  return (
    <ol className="divide-y rounded border">
      {STEPS.map((step, index) => {
        const isDone = done.has(step.state);
        const isNext = index === reached + 1;
        return (
          <li
            key={step.state}
            className={`p-3 text-sm ${isNext ? "bg-amber-50" : isDone ? "" : "opacity-50"}`}
          >
            <div className="flex items-baseline gap-2">
              <span className="font-medium">{step.title}</span>
              {isDone && <StatusBadge status="done" />}
              {isNext && <span className="text-xs text-amber-700">als nächstes</span>}
            </div>
            <p className="mt-1 text-xs text-slate-600">{step.note}</p>
          </li>
        );
      })}
    </ol>
  );
}

export function TenantOffboarding({
  tenantId,
  tenantSlug,
}: {
  tenantId: string;
  tenantSlug: string;
}) {
  const qc = useQueryClient();
  const [start, setStart] = useState({ reason: "", requested_by: "", grace_days: 30 });
  const [drop, setDrop] = useState({ dropped_by: "", approved_by: "" });
  const [confirmedBy, setConfirmedBy] = useState("");
  const [abortReason, setAbortReason] = useState("");

  const offQ = useQuery({
    queryKey: ["offboarding", tenantId],
    queryFn: () => getOffboarding(tenantId),
    retry: false,
  });
  const exportsQ = useQuery({
    queryKey: ["exports", tenantId],
    queryFn: () => listExports(tenantId),
    retry: false,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["offboarding", tenantId] });
    void qc.invalidateQueries({ queryKey: ["tenant", tenantId] });
    void qc.invalidateQueries({ queryKey: ["tenants"] });
  };

  const startM = useMutation({ mutationFn: () => startOffboarding(tenantId, start), onSuccess: invalidate });
  const deliverM = useMutation({
    mutationFn: (exportId: string) => recordExportDelivered(tenantId, exportId),
    onSuccess: invalidate,
  });
  const dropM = useMutation({ mutationFn: () => dropTenantData(tenantId, drop), onSuccess: invalidate });
  const keyM = useMutation({
    mutationFn: () => confirmKeyDestroyed(tenantId, confirmedBy),
    onSuccess: invalidate,
  });
  const purgeM = useMutation({ mutationFn: () => markPurged(tenantId), onSuccess: invalidate });
  const abortM = useMutation({
    mutationFn: () => abortOffboarding(tenantId, abortReason),
    onSuccess: invalidate,
  });

  if (offQ.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (offQ.isError) return <ErrorBox error={offQ.error} />;

  const off = offQ.data;

  // Der Erfassungsbogen erscheint in zwei Fällen: wenn nie eine Kündigung
  // erfasst war, und wenn die letzte **zurückgenommen** wurde. Der zweite Fall
  // ist der, den der erste Entwurf vergessen hat: ein Kunde, der zurückzieht
  // und ein Jahr später wirklich kündigt, wäre in der Oberfläche nicht mehr zu
  // bearbeiten gewesen — obwohl die API es annimmt (geprüft: 201).
  const startForm = (
      <section className="rounded border bg-white p-4">
        <h2 className="mb-2 font-semibold">Kündigung erfassen</h2>
        <p className="mb-3 text-sm text-slate-600">
          Damit beginnt ein Ablauf in fünf Schritten mit Fristen und Schranken. Der Kunde
          wird ab sofort nicht mehr bedient. Bis Schritt 3 ist alles zurücknehmbar.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            startM.mutate();
          }}
        >
          <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
            <label className="col-span-2 block">
              <span className="mb-1 block text-slate-600">Grund (Pflicht)</span>
              <input
                required
                minLength={3}
                value={start.reason}
                onChange={(e) => setStart({ ...start, reason: e.target.value })}
                placeholder="Kündigung per 31.12., Ticket 4711"
                className="w-full rounded border px-2 py-1"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-slate-600">Karenzzeit (Tage)</span>
              <input
                type="number"
                min={0}
                value={start.grace_days}
                onChange={(e) => setStart({ ...start, grace_days: Number(e.target.value) })}
                className="w-24 rounded border px-2 py-1 text-right"
              />
            </label>
            <label className="col-span-2 block">
              <span className="mb-1 block text-slate-600">Erfasst von</span>
              <input
                required
                value={start.requested_by}
                onChange={(e) => setStart({ ...start, requested_by: e.target.value })}
                className="w-full rounded border px-2 py-1"
              />
            </label>
          </div>
          {startM.isError && <ErrorBox error={startM.error} />}
          <button
            type="submit"
            disabled={startM.isPending}
            className="rounded border border-red-400 px-3 py-1 text-sm text-red-800 disabled:opacity-50"
          >
            Kündigung erfassen
          </button>
        </form>
      </section>
  );

  if (!off) return startForm;

  const readyExports = (exportsQ.data ?? []).filter(
    (x) => x.state === "ready" || x.state === "downloaded",
  );

  if (off.state === "aborted") {
    return (
      <div className="space-y-6">
        <section className="rounded border bg-white p-4">
          <div className="mb-2 flex items-baseline gap-3">
            <h2 className="font-semibold">Zurückgenommene Kündigung</h2>
            <StatusBadge status={off.state} />
          </div>
          <p className="text-sm text-slate-600">
            Erfasst {new Date(off.requested_at).toLocaleDateString()} von {off.requested_by}
            {" — „"}
            {off.reason}
            {"“, zurückgenommen "}
            {off.aborted_at ? new Date(off.aborted_at).toLocaleDateString() : "—"}
            {off.aborted_reason && <> mit dem Grund „{off.aborted_reason}“</>}.
          </p>
        </section>
        {startForm}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {off.warning && (
        <div className="rounded border-2 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">
          <span className="font-semibold">Achtung: </span>
          {off.warning}
        </div>
      )}

      <section className="rounded border bg-white p-4">
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="font-semibold">Kündigung</h2>
          <StatusBadge status={off.state} />
          <span className="text-xs text-slate-500">
            erfasst {new Date(off.requested_at).toLocaleDateString()} von {off.requested_by}
          </span>
        </div>
        <p className="mb-3 text-sm">„{off.reason}“</p>
        <Timeline offboarding={off} />
        <dl className="mt-3 grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1 text-xs">
          <dt className="text-slate-500">Karenzzeit bis</dt>
          <dd>{new Date(off.grace_until).toLocaleDateString()}</dd>
          {off.purge_due_at && (
            <>
              <dt className="text-slate-500">Alles gelöscht bis</dt>
              <dd className="font-medium">{new Date(off.purge_due_at).toLocaleDateString()}</dd>
            </>
          )}
          {off.key_id && (
            <>
              <dt className="text-slate-500">Vernichteter Schlüssel</dt>
              <dd className="font-mono">{off.key_id}</dd>
            </>
          )}
        </dl>
      </section>

      {off.state === "requested" && (
        <section className="rounded border bg-white p-4">
          <h2 className="mb-2 font-semibold">Schritt 2 · Export zustellen</h2>
          <p className="mb-3 text-sm text-slate-600">
            Zuerst im Reiter „Sicherungen“ einen Export bestellen und herunterladen, dann
            hier vermerken, dass er beim Kunden ist. Hieran hängt die Löschsperre.
          </p>
          {readyExports.length === 0 ? (
            <p className="text-sm text-amber-700">
              Kein fertiger Export vorhanden. Erst dort bestellen.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {readyExports.map((x) => (
                <li key={x.id} className="flex items-center gap-3">
                  <span className="font-mono text-xs">{x.path?.split("/").pop() ?? x.id}</span>
                  <StatusBadge status={x.state} />
                  <button
                    type="button"
                    onClick={() => deliverM.mutate(x.id)}
                    disabled={deliverM.isPending}
                    className="rounded border px-2 py-1 text-xs disabled:opacity-50"
                  >
                    Als zugestellt vermerken
                  </button>
                </li>
              ))}
            </ul>
          )}
          {deliverM.isError && <div className="mt-3"><ErrorBox error={deliverM.error} /></div>}
        </section>
      )}

      {off.state === "export_ready" && (
        <section className="rounded border border-red-300 bg-red-50 p-4">
          <h2 className="mb-2 font-semibold text-red-900">
            Schritt 3 · Schema und Rolle löschen
          </h2>
          <p className="mb-3 text-sm text-red-900">
            <span className="font-semibold">Unwiderruflich.</span> Danach sind die Daten
            dieses Kunden nur noch in den Sicherungen. Zwei verschiedene Personen — die
            API weist es ab, wenn beide Namen gleich sind.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              dropM.mutate();
            }}
          >
            <div className="mb-3 grid grid-cols-2 gap-3 text-sm">
              <label className="block">
                <span className="mb-1 block text-red-800">Ausgeführt von</span>
                <input
                  required
                  value={drop.dropped_by}
                  onChange={(e) => setDrop({ ...drop, dropped_by: e.target.value })}
                  className="w-full rounded border px-2 py-1"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-red-800">Freigegeben von</span>
                <input
                  required
                  value={drop.approved_by}
                  onChange={(e) => setDrop({ ...drop, approved_by: e.target.value })}
                  className="w-full rounded border px-2 py-1"
                />
              </label>
            </div>
            {dropM.isError && <ErrorBox error={dropM.error} />}
            <button
              type="submit"
              disabled={dropM.isPending || !drop.dropped_by || drop.dropped_by === drop.approved_by}
              className="rounded bg-red-700 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {dropM.isPending ? "Läuft…" : "Löschen"}
            </button>
            {drop.dropped_by !== "" && drop.dropped_by === drop.approved_by && (
              <span className="ml-3 text-xs text-red-800">
                Zwei verschiedene Personen.
              </span>
            )}
          </form>
        </section>
      )}

      {off.state === "dropped" && (
        <section className="rounded border border-red-300 bg-red-50 p-4">
          <h2 className="mb-2 font-semibold text-red-900">
            Schritt 4 · Kundenschlüssel vernichten
          </h2>
          <p className="mb-3 text-sm text-red-900">
            Zuerst <span className="font-mono">MAGISTER_TENANT_AUDIT_KEY_
            {tenantSlug.toUpperCase()}</span> aus der Umgebung des Anwendungsservers
            entfernen, den Prozess neu starten und den Wert aus dem Passwortspeicher
            löschen. <span className="font-semibold">Dann</span> hier bestätigen — die
            Bestätigung schreibt zugleich die Markierung auf den Share, die die kurze
            Frist auch für die Monatskopien gelten lässt.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              keyM.mutate();
            }}
          >
            <label className="mb-3 block text-sm">
              <span className="mb-1 block text-red-800">Bestätigt von</span>
              <input
                required
                value={confirmedBy}
                onChange={(e) => setConfirmedBy(e.target.value)}
                className="w-72 rounded border px-2 py-1"
              />
            </label>
            {keyM.isError && <ErrorBox error={keyM.error} />}
            <button
              type="submit"
              disabled={keyM.isPending}
              className="rounded bg-red-700 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              Vernichtung bestätigen
            </button>
          </form>
        </section>
      )}

      {off.state === "shredded" && (
        <section className="rounded border bg-white p-4">
          <h2 className="mb-2 font-semibold">Schritt 5 · Fristablauf vermerken</h2>
          <p className="mb-3 text-sm text-slate-600">
            Möglich ab {off.purge_due_at ? new Date(off.purge_due_at).toLocaleDateString() : "—"}.
            Vorher weigert sich der Endpunkt.
          </p>
          {purgeM.isError && <ErrorBox error={purgeM.error} />}
          <button
            type="button"
            onClick={() => purgeM.mutate()}
            disabled={purgeM.isPending}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            Fristablauf vermerken
          </button>
        </section>
      )}

      {(off.state === "requested" || off.state === "export_ready") && (
        <section className="rounded border bg-white p-4">
          <h2 className="mb-2 font-semibold">Zurücknehmen</h2>
          <p className="mb-3 text-xs text-slate-500">
            Möglich, solange nichts gelöscht ist. Der Kunde wird danach wieder bedient.
          </p>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              abortM.mutate();
            }}
          >
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">Grund (Pflicht)</span>
              <input
                required
                minLength={3}
                value={abortReason}
                onChange={(e) => setAbortReason(e.target.value)}
                className="w-96 rounded border px-2 py-1"
              />
            </label>
            <button
              type="submit"
              disabled={abortM.isPending}
              className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            >
              Kündigung zurücknehmen
            </button>
          </form>
          {abortM.isError && <div className="mt-3"><ErrorBox error={abortM.error} /></div>}
        </section>
      )}
    </div>
  );
}
