import { useQuery } from "@tanstack/react-query";

import { getTenantStatus, type StatusReport } from "../api/operations";
import { ErrorBox } from "./ErrorBox";

const PROFILE_LABEL: Record<string, string> = {
  school: "Schule",
  company: "Firma",
  neutral: "Neutral",
};

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "nie";
}

/** Wie alt eine Meldung ist, in Minuten — gemessen am Zeitpunkt der Antwort. */
function ageMinutes(iso: string | null, asOf: number): number | null {
  return iso ? Math.round((asOf - new Date(iso).getTime()) / 60000) : null;
}

export function AdSyncSummary({ ad }: { ad: StatusReport["ad"] }) {
  if (!ad) return <p className="text-sm text-slate-500">Keine Angabe zum AD-Abgleich.</p>;
  return (
    <dl className="grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1 text-sm">
      <dt className="text-slate-500">Weg zum AD</dt>
      <dd>{ad.backend === "connector" ? "AD-Connector (Agent beim Kunden)" : ad.backend ?? "—"}</dd>
      <dt className="text-slate-500">Eingerichtet</dt>
      <dd className={ad.configured ? "" : "text-red-700"}>
        {ad.configured
          ? "ja"
          : `nein — es fehlt: ${ad.missing.join(", ")} (Reiter Einstellungen → Active Directory)`}
      </dd>
      <dt className="text-slate-500">Letzter Abgleich ok</dt>
      <dd>
        {when(ad.last_success_at)}
        {ad.last_count !== null && ad.last_success_at ? ` · ${ad.last_count} Benutzer` : ""}
        {ad.last_mode ? ` · ${ad.last_mode === "full" ? "voll" : "inkrementell"}` : ""}
      </dd>
      <dt className="text-slate-500">Letzter Fehlschlag</dt>
      <dd
        className={
          ad.last_failure_at &&
          (!ad.last_success_at || ad.last_failure_at > ad.last_success_at)
            ? "text-red-700"
            : ""
        }
      >
        {when(ad.last_failure_at)}
      </dd>
    </dl>
  );
}

/**
 * Was die Installation des Kunden zuletzt gemeldet hat (ADR-0024 D1).
 *
 * Die Frage, die diese Ansicht beantwortet: kommt an, was hier eingestellt
 * ist? Vorher war das von der Konsole aus nicht zu sehen — „in der Konsole
 * auf Firma, im Portal Schule" fiel erst beim Kunden auf.
 */
export function TenantStatusPanel({ tenantId }: { tenantId: string }) {
  const q = useQuery({
    queryKey: ["tenant-status", tenantId],
    queryFn: () => getTenantStatus(tenantId),
    retry: false,
    refetchInterval: 30_000,
  });
  if (q.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (q.isError) return <ErrorBox error={q.error} />;
  const data = q.data;
  if (!data) return null;
  const report = data.report;
  const age = ageMinutes(data.reported_at, q.dataUpdatedAt);

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-3 font-semibold">Zustand der Installation</h2>
      {!report ? (
        <div className="rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="mb-1 font-medium">Die Installation hat sich noch nie gemeldet.</p>
          <p>
            Dann kommt auch nichts an, was hier eingestellt wird (Profil, Module, Einstellungen).
            Auf dem Anwendungsserver nachsehen:
          </p>
          <pre className="mt-2 overflow-x-auto rounded bg-white p-2 font-mono text-xs">
            docker compose --project-directory deploy/compose logs api | grep -iE
            "Soll-Zustand|Zustandsmeldung|Registry"
          </pre>
        </div>
      ) : (
        <div className="space-y-3">
          <dl className="grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-slate-500">Letzte Meldung</dt>
            <dd className={age !== null && age > 15 ? "text-amber-700" : ""}>
              {when(data.reported_at)}
              {age !== null && age > 15 ? ` — seit ${age} Minuten keine Meldung` : ""}
            </dd>
            <dt className="text-slate-500">Abgleich</dt>
            <dd className={report.reconcile.ok ? "text-emerald-700" : "text-red-700"}>
              {report.reconcile.ok ? "in Ordnung" : `gescheitert: ${report.reconcile.error ?? "?"}`}
            </dd>
            <dt className="text-slate-500">Profil</dt>
            <dd className={data.profile_matches === false ? "text-red-700" : ""}>
              {PROFILE_LABEL[report.effective_profile ?? ""] ?? report.effective_profile ?? "—"}
              {data.profile_matches === false
                ? ` — hier eingestellt: ${PROFILE_LABEL[data.console_profile] ?? data.console_profile}. Kommt beim nächsten Abgleich an, sofern der Abgleich läuft.`
                : ""}
            </dd>
            <dt className="text-slate-500">Module</dt>
            <dd className="font-mono text-xs">{report.enabled_modules.join(", ")}</dd>
            <dt className="text-slate-500">Entra-Client-Secret</dt>
            <dd>{report.secrets_present.oidc_client_secret ? "gesetzt" : "nicht gesetzt"}</dd>
          </dl>
          <div>
            <h3 className="mb-1 text-sm font-medium">AD-Abgleich</h3>
            <AdSyncSummary ad={report.ad} />
          </div>
        </div>
      )}
    </section>
  );
}
