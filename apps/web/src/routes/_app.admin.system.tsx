import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useAppSettings,
  useRequestRestart,
  useRequestUpdate,
  useSystemStatus,
  useUpdateAppSettings,
} from "@/api/hooks";
import type { AppSettingsOut } from "@/api/types";
import { DangerZoneCard } from "@/components/DangerZoneCard";
import { WebTlsCard } from "@/components/WebTlsCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useFormatters } from "@/lib/useFormatters";

export const Route = createFileRoute("/_app/admin/system")({
  component: SystemPage,
});

function SystemPage(): JSX.Element {
  const { t } = useTranslation();
  const settings = useAppSettings();
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("system.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("system.description")}</p>
      </header>

      {settings.data ? <WebTlsCard certSet={settings.data.web_tls_cert_set} /> : null}

      {settings.data ? <PasswordStoreCard data={settings.data} /> : null}

      <SystemOpsCard />

      <DangerZoneCard />
    </div>
  );
}

function PasswordStoreCard({ data }: { data: AppSettingsOut }): JSX.Element {
  const { t } = useTranslation();
  const update = useUpdateAppSettings();
  const [enabled, setEnabled] = useState(data.password_store_enabled);
  const [success, setSuccess] = useState(false);

  const dirty = enabled !== data.password_store_enabled;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.settings.password_store_title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {success ? (
          <div
            role="status"
            className="rounded-md border border-green-500/50 bg-green-500/10 px-3 py-2 text-sm text-green-700 dark:text-green-300"
          >
            {t("admin.settings.success")}
          </div>
        ) : null}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-input"
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              setSuccess(false);
            }}
          />
          <span>
            {t("admin.settings.password_store_enabled")}
            <span className="block text-xs text-muted-foreground">
              {t("admin.settings.password_store_hint")}
            </span>
          </span>
        </label>
        <div className="flex justify-end">
          <Button
            type="button"
            disabled={!dirty || update.isPending}
            onClick={() =>
              update.mutate(
                { password_store_enabled: enabled },
                { onSuccess: () => setSuccess(true) },
              )
            }
          >
            {update.isPending ? t("common.loading") : t("admin.settings.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function SystemOpsCard(): JSX.Element {
  const { t } = useTranslation();
  const fmt = useFormatters();
  const status = useSystemStatus();
  const restart = useRequestRestart();
  const update = useRequestUpdate();
  const [confirm, setConfirm] = useState<null | "restart" | "update">(null);

  const configured = status.data?.configured ?? false;
  const last = status.data?.last ?? null;
  const pending = status.data?.pending ?? 0;
  const log = status.data?.log ?? null;
  const busy = pending > 0 || last?.state === "running" || restart.isPending || update.isPending;

  const stateLabel = (state: string | null | undefined): string => {
    if (state === "success") return t("system.ops.state_success");
    if (state === "error") return t("system.ops.state_error");
    if (state === "running") return t("system.ops.state_running");
    if (state === "queued") return t("system.ops.state_queued");
    return state ?? "—";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("system.ops.title")}</CardTitle>
        <CardDescription>{t("system.ops.desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!configured ? (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            {t("system.ops.not_configured")}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {confirm === "update" ? (
            <>
              <span className="text-sm">{t("system.ops.update_confirm")}</span>
              <Button
                type="button"
                disabled={busy}
                onClick={() => update.mutate(undefined, { onSuccess: () => setConfirm(null) })}
              >
                {t("system.ops.update_yes")}
              </Button>
              <Button type="button" variant="outline" onClick={() => setConfirm(null)}>
                {t("common.cancel")}
              </Button>
            </>
          ) : confirm === "restart" ? (
            <>
              <span className="text-sm">{t("system.ops.restart_confirm")}</span>
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => restart.mutate(undefined, { onSuccess: () => setConfirm(null) })}
              >
                {t("system.ops.restart_yes")}
              </Button>
              <Button type="button" variant="outline" onClick={() => setConfirm(null)}>
                {t("common.cancel")}
              </Button>
            </>
          ) : (
            <>
              <Button
                type="button"
                disabled={!configured || busy}
                onClick={() => setConfirm("update")}
              >
                {t("system.ops.update_button")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!configured || busy}
                onClick={() => setConfirm("restart")}
              >
                {t("system.ops.restart_button")}
              </Button>
              {busy ? (
                <span className="text-sm text-muted-foreground">{t("system.ops.busy")}</span>
              ) : null}
            </>
          )}
        </div>

        <dl className="space-y-1 text-sm">
          <div className="flex gap-3">
            <dt className="w-40 shrink-0 text-muted-foreground">{t("system.ops.pending")}</dt>
            <dd className="font-medium">{pending}</dd>
          </div>
          {last ? (
            <>
              <div className="flex gap-3">
                <dt className="w-40 shrink-0 text-muted-foreground">
                  {t("system.ops.last_action")}
                </dt>
                <dd className="font-medium">
                  {last.action ?? "—"} · {stateLabel(last.state)}
                </dd>
              </div>
              {last.git_sha ? (
                <div className="flex gap-3">
                  <dt className="w-40 shrink-0 text-muted-foreground">{t("system.ops.version")}</dt>
                  <dd className="font-mono text-xs">{last.git_sha}</dd>
                </div>
              ) : null}
              {last.finished_at ? (
                <div className="flex gap-3">
                  <dt className="w-40 shrink-0 text-muted-foreground">
                    {t("system.ops.finished_at")}
                  </dt>
                  <dd className="font-medium">{fmt.formatDateTime(last.finished_at)}</dd>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-muted-foreground">{t("system.ops.no_history")}</p>
          )}
        </dl>

        {log ? (
          <div className="space-y-1">
            <p className="text-sm font-medium">{t("system.ops.log")}</p>
            <pre className="max-h-72 overflow-auto rounded-md border bg-muted/30 p-2 text-xs whitespace-pre-wrap">
              {log}
            </pre>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
