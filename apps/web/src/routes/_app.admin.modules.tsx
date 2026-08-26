import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAdminModules, useUpdateModules } from "@/api/hooks";
import type { AdminModuleOut, AdminModulesOut, ModuleSettingsUpdate } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/modules")({
  component: ModulesPage,
});

export function ModulesPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const q = useAdminModules();
  const update = useUpdateModules();
  // Switching the edition is a heavy change (module set + vocabulary flip), so
  // it never fires straight from the <select>: picking a new profile opens a
  // confirmation dialog with an effect preview and only commits on confirm.
  const [pendingProfile, setPendingProfile] = useState<string | null>(null);

  const applyModule = (patch: ModuleSettingsUpdate): void => update.mutate(patch);

  const confirmSwitch = (): void => {
    if (!pendingProfile) return;
    update.mutate(
      { instance_profile: pendingProfile },
      { onSuccess: () => setPendingProfile(null) },
    );
  };

  const cancelSwitch = (): void => {
    update.reset();
    setPendingProfile(null);
  };

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
                onChange={(e) => {
                  const next = e.target.value;
                  if (next !== q.data?.instance_profile) setPendingProfile(next);
                }}
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
                        onChange={(e) =>
                          applyModule({ module_overrides: { [m.id]: e.target.checked } })
                        }
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

          {update.isError && pendingProfile === null ? (
            <p className="text-sm text-destructive">{t("modules.save_error")}</p>
          ) : null}

          {pendingProfile !== null ? (
            <ProfileSwitchDialog
              data={q.data}
              target={pendingProfile}
              isPending={update.isPending}
              isError={update.isError}
              onCancel={cancelSwitch}
              onConfirm={confirmSwitch}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

const VOCAB_KEYS = ["unit", "group", "lead", "member"] as const;

/** Whether a module would be enabled under `profile`, matching the backend's
 *  `_is_on`: non-toggleable is always on; an explicit override wins; otherwise
 *  the module is on when the profile is one of its defaults. */
function enabledUnder(
  m: AdminModuleOut,
  overrides: Record<string, boolean>,
  profile: string,
): boolean {
  if (!m.toggleable) return true;
  if (Object.prototype.hasOwnProperty.call(overrides, m.id)) return overrides[m.id];
  return m.default_in_profiles.includes(profile);
}

function ProfileSwitchDialog({
  data,
  target,
  isPending,
  isError,
  onCancel,
  onConfirm,
}: {
  data: AdminModulesOut;
  target: string;
  isPending: boolean;
  isError: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const from = data.instance_profile;
  const overrides = data.module_overrides;

  const enables = data.modules.filter(
    (m) => m.toggleable && !m.enabled && enabledUnder(m, overrides, target),
  );
  const disables = data.modules.filter(
    (m) => m.toggleable && m.enabled && !enabledUnder(m, overrides, target),
  );

  const profileLabel = (p: string): string => t(`modules.profile_${p}`, { defaultValue: p });
  const moduleLabel = (m: AdminModuleOut): string =>
    t(`modules.mod_${m.id}`, { defaultValue: m.id });
  const vocab = (p: string, k: string): string => t(`terms.${p}.${k}`);

  return (
    <Dialog open onOpenChange={(next) => (!next ? onCancel() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("modules.switch_title")}</DialogTitle>
          <DialogDescription>
            {t("modules.switch_desc", { from: profileLabel(from), to: profileLabel(target) })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          {enables.length === 0 && disables.length === 0 ? (
            <p className="text-muted-foreground">{t("modules.switch_no_module_change")}</p>
          ) : (
            <div className="space-y-3">
              {enables.length > 0 ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground">
                    {t("modules.switch_enables")}
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {enables.map((m) => (
                      <li key={m.id} className="text-emerald-600 dark:text-emerald-400">
                        + {moduleLabel(m)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {disables.length > 0 ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground">
                    {t("modules.switch_disables")}
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {disables.map((m) => (
                      <li key={m.id} className="text-destructive">
                        − {moduleLabel(m)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}

          <div className="border-t pt-3">
            <div className="text-xs font-medium text-muted-foreground">
              {t("modules.switch_vocab")}
            </div>
            <dl className="mt-1 space-y-1">
              {VOCAB_KEYS.map((k) => (
                <div key={k} className="flex items-center gap-2">
                  <dd className="text-muted-foreground line-through">{vocab(from, k)}</dd>
                  <span aria-hidden>→</span>
                  <dd className="font-medium">{vocab(target, k)}</dd>
                </div>
              ))}
            </dl>
          </div>

          {isError ? <p className="text-destructive">{t("modules.save_error")}</p> : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>
            {t("common.cancel")}
          </Button>
          <Button type="button" onClick={onConfirm} disabled={isPending}>
            {isPending ? t("common.loading") : t("modules.switch_confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
