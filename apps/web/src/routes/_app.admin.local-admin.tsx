import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useChangeLocalAdminPassword, useLocalAdmin, useSetLocalAdminEnabled } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/local-admin")({
  component: LocalAdminPage,
});

const MIN_NEW_PASSWORD_LENGTH = 12;

function passwordChangeErrorKey(err: ApiError): string {
  if (err.status === 400) return "admin.local_admin.error_invalid_current";
  if (err.status === 404) return "admin.local_admin.error_not_configured";
  return "errors.generic";
}

function LocalAdminPage(): JSX.Element {
  const { t } = useTranslation();
  const status = useLocalAdmin();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.local_admin.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.local_admin.description")}</p>
      </header>

      {status.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : status.isError ? (
        <p className="text-destructive">
          {status.error instanceof ApiError && status.error.status === 404
            ? t("admin.local_admin.error_not_configured")
            : t("errors.generic")}
        </p>
      ) : status.data ? (
        <>
          <StatusCard status={status.data} />
          <ChangePasswordCard />
        </>
      ) : null}
    </div>
  );
}

function StatusCard({
  status,
}: {
  status: { username: string; enabled: boolean; locked_until: string | null };
}): JSX.Element {
  const { t } = useTranslation();
  const setEnabled = useSetLocalAdminEnabled();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.local_admin.status_title")}</CardTitle>
        <CardDescription>{status.username}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-sm">
          <span className="text-muted-foreground">{t("admin.local_admin.enabled_label")}: </span>
          <span className="font-medium">{status.enabled ? t("users.yes") : t("users.no")}</span>
        </div>
        {status.locked_until ? (
          <div className="text-sm text-destructive">
            {t("admin.local_admin.locked_until_label")}: {status.locked_until}
          </div>
        ) : null}
        <Button
          type="button"
          variant={status.enabled ? "destructive" : "default"}
          onClick={() => setEnabled.mutate(!status.enabled)}
          disabled={setEnabled.isPending}
        >
          {status.enabled
            ? t("admin.local_admin.disable_button")
            : t("admin.local_admin.enable_button")}
        </Button>
      </CardContent>
    </Card>
  );
}

function ChangePasswordCard(): JSX.Element {
  const { t } = useTranslation();
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [success, setSuccess] = useState(false);
  const change = useChangeLocalAdminPassword();

  const mismatch = newPw.length > 0 && confirmPw.length > 0 && newPw !== confirmPw;
  const tooShort = newPw.length > 0 && newPw.length < MIN_NEW_PASSWORD_LENGTH;
  const submitDisabled =
    change.isPending ||
    currentPw.length === 0 ||
    newPw.length < MIN_NEW_PASSWORD_LENGTH ||
    confirmPw !== newPw;

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    setSuccess(false);
    change.mutate(
      { current_password: currentPw, new_password: newPw },
      {
        onSuccess: () => {
          setSuccess(true);
          setCurrentPw("");
          setNewPw("");
          setConfirmPw("");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.local_admin.change_password_title")}</CardTitle>
        <CardDescription>{t("admin.local_admin.change_password_description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {change.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t(passwordChangeErrorKey(change.error))}
            </div>
          ) : null}
          {success ? (
            <div
              role="status"
              className="rounded-md border border-green-500/50 bg-green-500/10 px-3 py-2 text-sm text-green-700 dark:text-green-300"
            >
              {t("admin.local_admin.password_changed")}
            </div>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="current-password">
              {t("admin.local_admin.current_password_label")}
            </Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="new-password">{t("admin.local_admin.new_password_label")}</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              required
              minLength={MIN_NEW_PASSWORD_LENGTH}
            />
            {tooShort ? (
              <p className="text-xs text-destructive">
                {t("admin.local_admin.password_too_short", { min: MIN_NEW_PASSWORD_LENGTH })}
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="confirm-password">
              {t("admin.local_admin.confirm_password_label")}
            </Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              required
            />
            {mismatch ? (
              <p className="text-xs text-destructive">{t("admin.local_admin.password_mismatch")}</p>
            ) : null}
          </div>
          <Button type="submit" disabled={submitDisabled}>
            {change.isPending ? t("common.loading") : t("admin.local_admin.change_password_submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
