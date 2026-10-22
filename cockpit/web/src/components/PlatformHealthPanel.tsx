import { useQuery } from "@tanstack/react-query";

import { getPlatformHealth, type HealthItem } from "../api/platform";
import { ErrorBox } from "./ErrorBox";

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-label={ok ? "in Ordnung" : "Störung"}
      className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
    />
  );
}

function text(item: HealthItem, key: string): string {
  const v = item[key];
  if (v === undefined || v === null) return "";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

function Rows({
  title,
  items,
  label,
  detail,
}: {
  title: string;
  items: HealthItem[];
  label: (i: HealthItem) => string;
  detail: (i: HealthItem) => string;
}) {
  if (items.length === 0) return null;
  const bad = items.filter((i) => !i.ok).length;
  return (
    <div>
      <h3 className="mb-1 text-sm font-medium">
        {title}{" "}
        <span className={bad ? "text-red-700" : "text-slate-500"}>
          {bad ? `— ${bad} gestört` : "— alles in Ordnung"}
        </span>
      </h3>
      <ul className="divide-y rounded border text-sm">
        {items.map((i, n) => (
          <li key={n} className="flex items-start gap-3 px-3 py-1.5">
            <span className="mt-1.5">
              <Dot ok={i.ok} />
            </span>
            <span className="w-72 shrink-0">{label(i)}</span>
            <span className={i.ok ? "text-slate-600" : "text-red-700"}>{detail(i)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Überwachung des Plattform-Hosts: laufen die Dienste, lauschen die Ports,
 * antworten die Listener durch Caddy, wird jeder Kunde bedient?
 *
 * Erhoben vom Ops-Agenten auf dem Host, einmal je Minute. Die Konsole selbst
 * hat keinen Zugang zu Docker und zu den Ports — sie zeigt den Bericht und
 * sein Alter. Ein alter Bericht ist selbst ein Befund: dann läuft der Agent nicht.
 */
export function PlatformHealthPanel() {
  const q = useQuery({
    queryKey: ["platform-health"],
    queryFn: getPlatformHealth,
    refetchInterval: 15_000,
  });
  if (q.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (q.isError) return <ErrorBox error={q.error} />;
  const h = q.data;
  if (!h) return null;
  const r = h.report;

  return (
    <section className="rounded border bg-white p-4">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="font-semibold">Überwachung</h2>
        {r && !h.stale && (
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${
              r.ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"
            }`}
          >
            {r.ok ? "alles in Ordnung" : "Störung"}
          </span>
        )}
        {r && (
          <span className={`text-xs ${h.stale ? "text-amber-700" : "text-slate-500"}`}>
            {r.host} · erhoben vor {h.age_seconds ?? "?"} s
            {h.stale ? " — veraltet: läuft der Ops-Agent?" : ""}
          </span>
        )}
      </div>

      {!h.configured && (
        <div className="rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          Nicht eingerichtet (COCKPIT_OPS_DIR fehlt). Auf dem Plattform-Host als root:
          <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh ops-agent</pre>
        </div>
      )}
      {h.configured && !h.present && (
        <div className="rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          Noch kein Zustandsbericht. Der Ops-Agent erhebt ihn einmal je Minute — läuft er nicht,
          auf dem Plattform-Host als root einrichten:
          <pre className="mt-1 font-mono text-xs">./scripts/plattform-aufbau.sh ops-agent</pre>
          Protokoll: <code>journalctl -u magister-plattform-ops</code>
        </div>
      )}
      {h.error && (
        <pre className="mb-3 max-h-32 overflow-auto rounded bg-red-50 p-2 font-mono text-xs text-red-800">
          {h.error}
        </pre>
      )}

      {r && (
        <div className="space-y-4">
          <Rows
            title="Dienste"
            items={r.services}
            label={(i) => `${text(i, "stack")} · ${text(i, "service")}`}
            detail={(i) => text(i, "status") || text(i, "state")}
          />
          <Rows
            title="Ports"
            items={r.ports}
            label={(i) => `${text(i, "port")} · ${text(i, "purpose")}`}
            detail={(i) =>
              text(i, "detail") || (i.listening ? `lauscht (${text(i, "by") || "Docker"})` : "")
            }
          />
          <Rows
            title="Antworten durch Caddy"
            items={r.probes}
            label={(i) => text(i, "name")}
            detail={(i) => `${text(i, "detail")} (HTTP ${text(i, "http")})`}
          />
          <Rows
            title="Zertifikate"
            items={r.certificates}
            label={(i) => `${text(i, "purpose")} (${text(i, "name")})`}
            detail={(i) => text(i, "detail") || `noch ${text(i, "days_left")} Tage`}
          />
          <Rows
            title="Platte"
            items={r.disk}
            label={(i) => text(i, "path")}
            detail={(i) => `${text(i, "used_pct")} % belegt`}
          />
        </div>
      )}
    </section>
  );
}
