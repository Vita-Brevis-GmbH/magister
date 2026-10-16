import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getTenantModules, putTenantModules, type TenantModulesUpdate } from "../api/modules";
import type { TenantProfile } from "../api/tenants";
import { ErrorBox } from "../components/ErrorBox";

const PROFILE_LABEL: Record<TenantProfile, string> = {
  school: "Schule",
  company: "Firma",
  neutral: "Neutral",
};

const MODULE_LABEL: Record<string, string> = {
  platform: "Plattform",
  ad: "AD",
  users: "Benutzer",
  settings: "Einstellungen",
  templates: "Vorlagen & Briefe",
  classes: "Klassen",
  imports: "Importe",
  departments: "Abteilungen",
  reports: "Berichte",
  devices: "Geräte",
};

/**
 * Profil und Module eines Kunden (ADR-0008, ADR-0017).
 *
 * Gehostet ist das hier der **einzige** Ort, an dem sie sich ändern lassen.
 * Beim Kunden ist die Seite „Module & Funktionen" dann nur lesbar: vorher
 * gab es beide Wege, und der Abgleich stellte die Änderung des Kunden beim
 * nächsten Lauf still zurück.
 *
 * Wirkt nicht sofort: die Datenebene holt den Soll-Zustand beim nächsten
 * Abgleich ab und schreibt dann ein `settings_pushed` ins Kundenprotokoll.
 */
export function TenantModules({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["tenant-modules", tenantId],
    queryFn: () => getTenantModules(tenantId),
    retry: false,
  });
  const m = useMutation({
    mutationFn: (body: TenantModulesUpdate) => putTenantModules(tenantId, body),
    onSuccess: (data) => {
      qc.setQueryData(["tenant-modules", tenantId], data);
      void qc.invalidateQueries({ queryKey: ["tenant", tenantId] });
      void qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  if (q.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (q.isError) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  const data = q.data;

  return (
    <div className="space-y-6">
      <section className="rounded border bg-white p-4">
        <h2 className="mb-2 font-semibold">Profil</h2>
        <p className="mb-3 text-xs text-slate-500">
          Setzt das Vokabular und die Module, die ohne eigenen Schalter gelten. Ein
          Wechsel löscht keine Daten: ein abgeschaltetes Modul behält sie und zeigt
          sie wieder, sobald es eingeschaltet wird.
        </p>
        <select
          aria-label="Profil"
          value={data.profile}
          disabled={m.isPending}
          onChange={(e) => {
            const next = e.target.value as TenantProfile;
            if (next === data.profile) return;
            if (
              window.confirm(
                `Profil von „${PROFILE_LABEL[data.profile]}" auf „${PROFILE_LABEL[next]}" ändern? ` +
                  "Module ohne eigenen Schalter und das Vokabular folgen beim nächsten Abgleich.",
              )
            ) {
              m.mutate({ profile: next });
            }
          }}
          className="rounded border px-2 py-1 text-sm"
        >
          {data.known_profiles.map((p) => (
            <option key={p} value={p}>
              {PROFILE_LABEL[p] ?? p}
            </option>
          ))}
        </select>
        {data.profile_source === "override" && (
          <p className="mt-2 text-xs text-amber-700">
            Das Profil kommt aus einer Abweichung in den Einstellungen
            (<code>instance_profile</code>). Ein Wechsel hier hebt sie auf.
          </p>
        )}
      </section>

      <section className="rounded border bg-white">
        <h2 className="border-b px-4 py-2 font-semibold">Module</h2>
        <ul className="divide-y">
          {data.modules.map((mod) => (
            <li key={mod.id} className="flex items-center justify-between gap-4 px-4 py-2 text-sm">
              <div>
                <div className="font-medium">{MODULE_LABEL[mod.id] ?? mod.id}</div>
                <div className="text-xs text-slate-500">
                  {!mod.toggleable
                    ? "Basis, immer an"
                    : mod.override === null
                      ? `vom Profil: ${mod.enabled ? "an" : "aus"}`
                      : `eigener Schalter: ${mod.override ? "an" : "aus"}`}
                </div>
              </div>
              {mod.toggleable && (
                <div className="flex items-center gap-2">
                  <label className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      aria-label={`${MODULE_LABEL[mod.id] ?? mod.id} an`}
                      checked={mod.enabled}
                      disabled={m.isPending}
                      onChange={(e) =>
                        m.mutate({ module_overrides: { [mod.id]: e.target.checked } })
                      }
                    />
                    <span className="text-slate-600">{mod.enabled ? "an" : "aus"}</span>
                  </label>
                  {mod.override !== null && (
                    <button
                      type="button"
                      disabled={m.isPending}
                      onClick={() => m.mutate({ module_overrides: { [mod.id]: null } })}
                      className="rounded border px-2 py-0.5 text-xs disabled:opacity-50"
                    >
                      Profil entscheiden lassen
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      {m.isError && <ErrorBox error={m.error} />}
      <p className="text-xs text-slate-500">
        Wirkt beim nächsten Abgleich der Datenebene; im Protokoll des Kunden steht
        dann <code>settings_pushed</code> mit altem und neuem Stand.
      </p>
    </div>
  );
}
