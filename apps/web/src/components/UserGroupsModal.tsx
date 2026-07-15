import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAdGroups, useUpdateUserGroups } from "@/api/hooks";
import type { AdUserOut } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { displayLabel } from "@/lib/userDisplay";

interface Props {
  /** When non-null the modal is open for the given user. Pass null to close. */
  user: AdUserOut | null;
  onClose: () => void;
}

function errorKey(err: ApiError): string {
  if (err.status === 409 && err.code === "user_not_in_ad") return "user_groups.error_not_in_ad";
  if (err.status === 503 && err.code === "ad_unavailable") return "errors.ad_unavailable";
  if (err.status === 403) return "errors.forbidden";
  return "errors.generic";
}

export function UserGroupsModal({ user, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const open = user !== null;
  const guid = user?.ad_object_guid ?? "";
  const groups = useAdGroups();
  const update = useUpdateUserGroups(guid);

  const [selected, setSelected] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);

  useEffect(() => {
    if (open && user) {
      setSelected([...user.ad_groups]);
      setFailed([]);
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, guid]);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!user) return;
    update.mutate(
      { groups: selected },
      {
        onSuccess: (res) => {
          // Some group writes may have been refused (no directory permission).
          // Keep the modal open to surface those; otherwise close.
          if (res.failed.length > 0) {
            setFailed(res.failed);
            setSelected(res.groups);
          } else {
            onClose();
          }
        },
      },
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
          <DialogTitle>{t("user_groups.title")}</DialogTitle>
          <DialogDescription>{user ? displayLabel(user) : ""}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {update.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t(errorKey(update.error))}
            </div>
          ) : null}

          {failed.length > 0 ? (
            <div className="rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              {t("user_groups.partial_failed", { count: failed.length })}
            </div>
          ) : null}

          <GroupPicker
            hint={t("user_groups.pick_hint")}
            catalog={groups.data ?? []}
            selected={selected}
            onChange={(next) => {
              setSelected(next);
              setFailed([]);
            }}
          />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={update.isPending}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending || !user}>
              {update.isPending ? t("common.loading") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
