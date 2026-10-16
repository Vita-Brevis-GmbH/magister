import { useQuery } from "@tanstack/react-query";

import { getFleetReport, type FleetFinding, type Severity } from "../api/fleet";
import { ErrorBox } from "../components/ErrorBox";

/**
 * Die Flotte: was jemand ansehen muss (ADR-0021 D6).
 *
 * Diese Ansicht ist **nicht** der Alarm. Der kommt aus
 * `cockpit_api.cli.fleet_check` über einen Exit-Code, den die bestehende
 * Überwachung liest — eine Oberfläche alarmiert nur den, der sie ohnehin
 * geöffnet hat. Hier steht, was dahinter steckt, wenn der Alarm kam.
 *
 * Sortiert kommt die Liste vom Server (schwerste zuerst), und `worst` ist
 * derselbe Wert wie der Exit-Code. Beides absichtlich nicht hier gerechnet:
 * eine Oberfläche, die den Schweregrad selbst bestimmt, bestimmt ihn eines
 * Tages anders als die Überwachung.
 */
export function Fleet() {
  const reportQ = useQuery({ queryKey: ["fleet"], queryFn: getFleetReport, retry: false });

  if (reportQ.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (reportQ.isError) return <ErrorBox error={reportQ.error} />;
  const report = reportQ.data;
  if (!report) return null;

  const critical = report.findings.filter((f) => f.severity === "critical");
  const warnings = report.findings.filter((f) => f.severity === "warning");

  return (
    <div className="space-y-6 text-sm">
      <div>
        <h2 className="text-lg font-semibold">Flotte</h2>
        <p className="mt-1 max-w-2xl text-slate-600">
          Agenten, Zertifikate und Lücken. Dieselben Befunde liefert{" "}
          <code className="whitespace-nowrap font-mono text-xs">
            python -m cockpit_api.cli.fleet_check
          </code>{" "}
          mit Exit-Code für die Überwachung — hier stehen sie zum Nachsehen.
        </p>
      </div>

      <Summary critical={critical.length} warnings={warnings.length} worst={report.worst} />

      {report.findings.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b bg-slate-50 text-left">
                <th className="px-3 py-2 font-semibold">Stufe</th>
                <th className="px-3 py-2 font-semibold">Kunde</th>
                <th className="px-3 py-2 font-semibold">Agent</th>
                <th className="px-3 py-2 font-semibold">Befund</th>
              </tr>
            </thead>
            <tbody>
              {report.findings.map((finding, index) => (
                <Row key={`${finding.kind}-${finding.tenant_slug}-${index}`} finding={finding} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Summary({
  critical,
  warnings,
  worst,
}: {
  critical: number;
  warnings: number;
  worst: number;
}) {
  if (worst === 0) {
    return (
      <p className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-emerald-900">
        Flotte in Ordnung: keine Befunde.
      </p>
    );
  }
  const tone =
    worst >= 2
      ? "border-red-300 bg-red-50 text-red-900"
      : "border-amber-400 bg-amber-50 text-amber-900";
  return (
    <p className={`rounded border px-3 py-2 ${tone}`}>
      <strong>
        {critical} kritisch, {warnings} Warnung{warnings === 1 ? "" : "en"}.
      </strong>{" "}
      {worst >= 2
        ? "Etwas davon kostet heute einen Passwort-Reset."
        : "Nichts brennt, aber es bleibt nicht von selbst gut."}
    </p>
  );
}

const LABEL: Record<Severity, string> = {
  critical: "kritisch",
  warning: "Warnung",
};

function Row({ finding }: { finding: FleetFinding }) {
  const tone =
    finding.severity === "critical"
      ? "bg-red-100 text-red-900"
      : "bg-amber-100 text-amber-900";
  return (
    <tr className="border-b align-top">
      <td className="px-3 py-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone}`}>
          {LABEL[finding.severity]}
        </span>
      </td>
      {/* `whitespace-nowrap`: ohne das bricht „dc01-thun“ am Bindestrich um,
          und ein Agentenname auf zwei Zeilen liest sich wie zwei Agenten. */}
      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{finding.tenant_slug}</td>
      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{finding.agent_name ?? "—"}</td>
      <td className="px-3 py-2">
        {finding.detail}
        {/* Die Art steht klein daneben: danach sucht man im Runbook, und ein
            Überwachungssystem kann einzelne Arten ausblenden. */}
        <span className="ml-2 font-mono text-xs text-slate-400">{finding.kind}</span>
      </td>
    </tr>
  );
}
