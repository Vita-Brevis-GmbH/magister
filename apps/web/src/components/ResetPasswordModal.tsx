import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useResetStudentPassword } from "@/api/hooks";
import type {
  AdUserOut,
  StudentPasswordResetMode,
  StudentPasswordResetResponse,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Props {
  /** When non-null the modal is open for the given student. Pass null to close. */
  student: AdUserOut | null;
  onClose: () => void;
}

const MIN_MANUAL_LENGTH = 12;

function errorKey(err: ApiError): string {
  if (err.status === 403) return "errors.forbidden";
  if (err.status === 404) return "password_reset.error_student_not_found";
  if (err.status === 429) return "errors.rate_limited";
  if (err.status === 422) return "password_reset.error_password_policy";
  if (err.status === 503 && err.code === "ad_unavailable") return "errors.ad_unavailable";
  if (err.status === 409 && err.code === "student_disabled")
    return "password_reset.error_student_disabled";
  if (err.status === 409 && err.code === "student_not_in_ad")
    return "password_reset.error_student_not_in_ad";
  if (err.status === 400 && err.code === "not_a_student")
    return "password_reset.error_not_a_student";
  return "errors.generic";
}

export function ResetPasswordModal({ student, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const open = student !== null;
  const guid = student?.ad_object_guid ?? "";
  const reset = useResetStudentPassword(guid);

  const [mode, setMode] = useState<StudentPasswordResetMode>("generate");
  const [manualPassword, setManualPassword] = useState("");
  const [forceChange, setForceChange] = useState(true);
  const [result, setResult] = useState<StudentPasswordResetResponse | null>(null);
  const [copied, setCopied] = useState(false);

  // Reset internal state every time the modal is (re-)opened for a new student.
  useEffect(() => {
    if (open) {
      setMode("generate");
      setManualPassword("");
      setForceChange(true);
      setResult(null);
      setCopied(false);
      reset.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, guid]);

  const submitDisabled =
    reset.isPending || (mode === "manual" && manualPassword.length < MIN_MANUAL_LENGTH) || !student;

  function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!student) return;
    reset.mutate(
      {
        mode,
        force_change: forceChange,
        ...(mode === "manual" && { manual_password: manualPassword }),
      },
      { onSuccess: (data) => setResult(data) },
    );
  }

  async function copyTempPassword(): Promise<void> {
    if (!result?.temp_password) return;
    await navigator.clipboard.writeText(result.temp_password);
    setCopied(true);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("password_reset.title")}</DialogTitle>
          <DialogDescription>
            {student ? student.upn : ""}
            {student?.given_name || student?.surname
              ? ` — ${[student.given_name, student.surname].filter(Boolean).join(" ")}`
              : ""}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-4">
            {result.mode === "generate" && result.temp_password ? (
              <>
                <p className="text-sm">{t("password_reset.success_generate_intro")}</p>
                <div className="flex items-center gap-2">
                  <code
                    className="flex-1 select-all rounded-md border bg-muted px-3 py-2 font-mono text-sm"
                    aria-label={t("password_reset.temp_password_label")}
                  >
                    {result.temp_password}
                  </code>
                  <Button type="button" variant="outline" size="sm" onClick={copyTempPassword}>
                    {copied ? t("password_reset.copied") : t("password_reset.copy")}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("password_reset.success_generate_note")}
                </p>
              </>
            ) : (
              <p className="text-sm">{t("password_reset.success_manual")}</p>
            )}
            <DialogFooter>
              <Button type="button" onClick={onClose}>
                {t("common.close")}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {reset.isError ? (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t(errorKey(reset.error))}
              </div>
            ) : null}

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("password_reset.mode_label")}</legend>
              <div className="flex flex-col gap-2">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="mode"
                    value="generate"
                    checked={mode === "generate"}
                    onChange={() => setMode("generate")}
                    className="mt-1"
                  />
                  <span>
                    <span className="font-medium">{t("password_reset.mode_generate")}</span>
                    <span className="block text-xs text-muted-foreground">
                      {t("password_reset.mode_generate_desc")}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="mode"
                    value="manual"
                    checked={mode === "manual"}
                    onChange={() => setMode("manual")}
                    className="mt-1"
                  />
                  <span>
                    <span className="font-medium">{t("password_reset.mode_manual")}</span>
                    <span className="block text-xs text-muted-foreground">
                      {t("password_reset.mode_manual_desc")}
                    </span>
                  </span>
                </label>
              </div>
            </fieldset>

            {mode === "manual" ? (
              <div className="space-y-1">
                <Label htmlFor="manual-password">{t("password_reset.manual_password_label")}</Label>
                <Input
                  id="manual-password"
                  type="text"
                  autoComplete="new-password"
                  minLength={MIN_MANUAL_LENGTH}
                  value={manualPassword}
                  onChange={(e) => setManualPassword(e.target.value)}
                  required
                />
                <p className="text-xs text-muted-foreground">
                  {t("password_reset.manual_password_hint", { min: MIN_MANUAL_LENGTH })}
                </p>
              </div>
            ) : null}

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={forceChange}
                onChange={(e) => setForceChange(e.target.checked)}
              />
              <span>{t("password_reset.force_change_label")}</span>
            </label>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={submitDisabled}>
                {reset.isPending ? t("common.loading") : t("password_reset.submit")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
