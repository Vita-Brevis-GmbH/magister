import { useState } from "react";
import { useTranslation } from "react-i18next";

import { usePurgeDemoData, useResetActivityLog } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Destructive maintenance actions: purge demo data + reset the activity log. */
export function DangerZoneCard(): JSX.Element {
  const { t } = useTranslation();
  const purge = usePurgeDemoData();
  const resetActivity = useResetActivityLog();
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-base text-destructive">
          {t("admin.settings.danger_title")}
        </CardTitle>
        <CardDescription>{t("admin.settings.purge_demo_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          {confirmPurge ? (
            <>
              <span className="text-sm text-destructive">
                {t("admin.settings.purge_demo_confirm")}
              </span>
              <Button
                type="button"
                variant="destructive"
                disabled={purge.isPending}
                onClick={() => purge.mutate(undefined, { onSuccess: () => setConfirmPurge(false) })}
              >
                {t("admin.settings.purge_demo_yes")}
              </Button>
              <Button type="button" variant="outline" onClick={() => setConfirmPurge(false)}>
                {t("common.cancel")}
              </Button>
            </>
          ) : (
            <Button type="button" variant="outline" onClick={() => setConfirmPurge(true)}>
              {t("admin.settings.purge_demo_button")}
            </Button>
          )}
          {purge.data ? (
            <span className="text-sm text-emerald-700">
              {purge.data.found
                ? t("admin.settings.purge_demo_ok", {
                    classes: purge.data.classes,
                    users: purge.data.users,
                  })
                : t("admin.settings.purge_demo_none")}
            </span>
          ) : purge.isError ? (
            <span className="text-sm text-destructive">{t("errors.generic")}</span>
          ) : null}
        </div>

        <div className="border-t pt-3">
          <p className="mb-2 text-sm font-medium">{t("admin.settings.reset_activity_title")}</p>
          <p className="mb-2 text-sm text-muted-foreground">
            {t("admin.settings.reset_activity_desc")}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {confirmReset ? (
              <>
                <span className="text-sm text-destructive">
                  {t("admin.settings.reset_activity_confirm")}
                </span>
                <Button
                  type="button"
                  variant="destructive"
                  disabled={resetActivity.isPending}
                  onClick={() =>
                    resetActivity.mutate(undefined, { onSuccess: () => setConfirmReset(false) })
                  }
                >
                  {t("admin.settings.reset_activity_yes")}
                </Button>
                <Button type="button" variant="outline" onClick={() => setConfirmReset(false)}>
                  {t("common.cancel")}
                </Button>
              </>
            ) : (
              <Button type="button" variant="outline" onClick={() => setConfirmReset(true)}>
                {t("admin.settings.reset_activity_button")}
              </Button>
            )}
            {resetActivity.data ? (
              <span className="text-sm text-emerald-700">
                {t("admin.settings.reset_activity_ok", {
                  deleted: resetActivity.data.deleted,
                  imports: resetActivity.data.imports_deleted,
                })}
              </span>
            ) : resetActivity.isError ? (
              <span className="text-sm text-destructive">{t("errors.generic")}</span>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
