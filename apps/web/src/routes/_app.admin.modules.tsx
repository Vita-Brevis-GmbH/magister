import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useAdminModules, useUpdateModules } from "@/api/hooks";
import type { ModuleSettingsUpdate } from "@/api/types";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/modules")({
  component: ModulesPage,
});

function ModulesPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const q = useAdminModules();
  const update = useUpdateModules();

  const apply = (patch: ModuleSettingsUpdate): void => update.mutate(patch);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("modules.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("modules.intro")}</p>
      </header>

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : q.isLoading || !q.data ? (
        <p className="text-sm text-muted-foreground">{t("modules.loading")}</p>
      ) : (
        <>
          <section className="space-y-3 rounded-md border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-sm font-medium">{t("modules.profile_label")}</h2>
                <p className="text-xs text-muted-foreground">{t("modules.profile_hint")}</p>
              </div>
              <select
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={q.data.instance_profile}
                disabled={update.isPending}
                onChange={(e) => apply({ instance_profile: e.target.value })}
              >
                {q.data.known_profiles.map((p) => (
                  <option key={p} value={p}>
                    {t(`modules.profile_${p}`, { defaultValue: p })}
                  </option>
                ))}
              </select>
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t pt-3 text-sm sm:grid-cols-4">
              <VocabItem label={t("modules.vocab_unit")} value={terms.unit} />
              <VocabItem label={t("modules.vocab_group")} value={terms.group} />
              <VocabItem label={t("modules.vocab_lead")} value={terms.lead} />
              <VocabItem label={t("modules.vocab_member")} value={terms.member} />
            </dl>
          </section>

          <section className="rounded-md border bg-card">
            <h2 className="border-b px-4 py-2 text-sm font-medium">{t("modules.modules_label")}</h2>
            <ul className="divide-y">
              {q.data.modules.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div>
                    <div className="text-sm font-medium">
                      {t(`modules.mod_${m.id}`, { defaultValue: m.id })}
                    </div>
                    {m.depends_on.length > 0 ? (
                      <div className="text-xs text-muted-foreground">
                        {t("modules.requires", { deps: m.depends_on.join(", ") })}
                      </div>
                    ) : null}
                  </div>
                  {m.toggleable ? (
                    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={m.enabled}
                        disabled={update.isPending}
                        onChange={(e) => apply({ module_overrides: { [m.id]: e.target.checked } })}
                      />
                      <span className="text-muted-foreground">
                        {m.enabled ? t("modules.on") : t("modules.off")}
                      </span>
                    </label>
                  ) : (
                    <span className="text-xs text-muted-foreground">{t("modules.always_on")}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {update.isError ? (
            <p className="text-sm text-destructive">{t("modules.save_error")}</p>
          ) : null}
        </>
      )}
    </div>
  );
}

function VocabItem({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
