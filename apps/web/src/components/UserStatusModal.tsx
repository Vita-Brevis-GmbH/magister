import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useSetUserStatus } from "@/api/hooks";
import type { AdUserOut } from "@/api/types";
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
import { displayLabel } from "@/lib/userDisplay";

interface Props {
  /** When non-null the modal is open for the given user. Pass null to close. */
  user: AdUserOut | null;
  onClose: () => void;
}

const MAX_REASON_LENGTH = 500;

function errorKey(err: ApiError): string {
  if (err.status === 400 && err.code === "cannot_disable_self")
    return "user_status.error_cannot_disable_self";
  if (err.status === 404) return "user_status.error_not_found";
  if (err.status === 409 && err.code === "user_not_in_ad")
    return "user_status.error_user_not_in_ad";
  if (err.status === 429) return "errors.rate_limited";
  if (err.status === 503 && err.code === "ad_unavailable") return "errors.ad_unavailable";
  return "errors.generic";
}

export function UserStatusModal({ user, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const open = user !== null;
  const guid = user?.ad_object_guid ?? "";
  const setStatus = useSetUserStatus(guid);

  // The action toggles the *current* state: disable when enabled, enable when disabled.
  const targetEnabled = user ? !user.enabled : true;
  const isDisableAction = user ? user.enabled : false;

  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) {
      setReason("");
      setStatus.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, guid]);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!user) return;
    setStatus.mutate(
      {
        enabled: targetEnabled,
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      },
      { onSuccess: () => onClose() },
    );
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
          <DialogTitle>
            {isDisableAction ? t("user_status.title_disable") : t("user_status.title_enable")}
          </DialogTitle>
          <DialogDescription>{user ? displayLabel(user) : ""}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {setStatus.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t(errorKey(setStatus.error))}
            </div>
          ) : null}

          <p className="text-sm text-muted-foreground">
            {isDisableAction
              ? t("user_status.consequence_disable")
              : t("user_status.consequence_enable")}
          </p>

          <div className="space-y-1.5">
            <Label htmlFor="user-status-reason">{t("user_status.reason_label")}</Label>
            <Input
              id="user-status-reason"
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={MAX_REASON_LENGTH}
              placeholder={t("user_status.reason_placeholder")}
            />
            <p className="text-xs text-muted-foreground">{t("user_status.reason_hint")}</p>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={setStatus.isPending}>
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              variant={isDisableAction ? "destructive" : "default"}
              disabled={setStatus.isPending || !user}
            >
              {setStatus.isPending
                ? t("user_status.submitting")
                : isDisableAction
                  ? t("user_status.confirm_disable")
                  : t("user_status.confirm_enable")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
