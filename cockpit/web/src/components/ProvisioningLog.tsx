import type { ProvisioningJob, ProvisioningStep } from "../api/tenants";
import { Badge, StatusBadge } from "./Badge";

/** Die fünf Schritte in ihrer Reihenfolge (ADR-0013 D2). */
const STEP_ORDER = ["create_role", "create_schema", "migrate", "data_key", "activate"] as const;

const STEP_LABEL: Record<string, string> = {
  create_role: "Anmelderolle anlegen",
  create_schema: "Schema anlegen",
  migrate: "Migrationen einspielen",
  data_key: "Kundenschlüssel erzeugen",
  activate: "Freischalten",
};

function stepStatus(steps: ProvisioningStep[], name: string): ProvisioningStep | undefined {
  // Der letzte Eintrag zu einem Schritt gewinnt: bei einem Wiederaufnehmen
  // steht derselbe Schritt zweimal im Protokoll, und interessant ist der
  // neuere Stand.
  return [...steps].reverse().find((s) => s.step === name);
}

/**
 * Das Protokoll des Bereitstellungs-Auftrags.
 *
 * Zeigt **alle fünf** Schritte, auch die noch nicht gelaufenen. Nur die
 * ausgeführten zu zeigen wäre kürzer und würde die Frage offenlassen, die man
 * an dieser Stelle hat: wie weit ist es, und was kommt noch.
 */
export function ProvisioningLog({
  job,
  nextStep,
}: {
  job: ProvisioningJob;
  nextStep: string | null;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-3">
        <h3 className="font-semibold">Bereitstellung</h3>
        <StatusBadge status={job.status} />
        {job.attempts > 1 && (
          <span className="text-xs text-slate-500">{job.attempts} Versuche</span>
        )}
      </div>

      <ol className="mb-3 divide-y rounded border">
        {STEP_ORDER.map((name) => {
          const entry = stepStatus(job.steps, name);
          const isNext = nextStep === name;
          return (
            <li
              key={name}
              className={`flex items-baseline gap-3 p-2 text-sm ${isNext ? "bg-amber-50" : ""}`}
            >
              <span className="w-6 font-mono text-xs text-slate-400">
                {STEP_ORDER.indexOf(name) + 1}
              </span>
              <span className="w-52 font-medium">{STEP_LABEL[name] ?? name}</span>
              <span className="w-24">
                {entry ? (
                  <Badge tone={entry.ok ? "ok" : "bad"}>
                    {entry.ok ? "geglückt" : "gescheitert"}
                  </Badge>
                ) : (
                  <span className="text-xs text-slate-400">offen</span>
                )}
              </span>
              <span className="flex-1 text-xs text-slate-600">
                {entry?.detail ?? (isNext ? "hier geht es weiter" : "")}
              </span>
              <span className="font-mono text-xs text-slate-400">
                {entry?.at ? new Date(entry.at).toLocaleTimeString() : ""}
              </span>
            </li>
          );
        })}
      </ol>

      {job.last_error && (
        <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          <span className="font-medium">Zuletzt geglückt: </span>
          <span className="font-mono">{job.last_completed_step ?? "kein Schritt"}</span>
          {" — danach: "}
          {job.last_error}
        </p>
      )}
    </div>
  );
}
