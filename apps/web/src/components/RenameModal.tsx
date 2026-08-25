import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useRenameApply, useRenamePreview } from "@/api/hooks";
import type { AdUserOut, RenameApplyRequest } from "@/api/types";
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
  user: AdUserOut | null;
  /** Admin may change UPN/sAMAccountName; SMI may not (backend enforces too). */
  canChangeLogin: boolean;
  onClose: () => void;
}

interface Draft {
  given_name: string;
  surname: string;
  display_name: string;
  upn: string;
  mail: string;
  sam_account_name: string;
  keep_old_mail_as_alias: boolean;
}

function errorKey(err: ApiError): string {
  if (err.status === 403 && err.code.startsWith("admin_only_field"))
    return "rename.error_admin_only";
  if (err.status === 409 && err.code.startsWith("upn_conflict")) return "rename.error_upn_conflict";
  if (err.status === 422 && err.code.startsWith("domain_not_allowed")) return "rename.error_domain";
  if (err.status === 422 && err.code.startsWith("mail_domains_not_configured"))
    return "users.detail.error_mail_domains_missing";
  if (err.status === 422 && err.code.startsWith("rename_invalid")) return "rename.error_invalid";
  if (err.status === 429) return "errors.rate_limited";
  if (err.status === 503 && err.code === "ad_unavailable") return "errors.ad_unavailable";
  return "errors.generic";
}

export function RenameModal({ user, canChangeLogin, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const open = user !== null;
  const guid = user?.ad_object_guid ?? "";
  const preview = useRenamePreview(guid);
  const apply = useRenameApply(guid);

  const [newSurname, setNewSurname] = useState("");
  const [newGiven, setNewGiven] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [oldMail, setOldMail] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setNewSurname("");
      setNewGiven(user?.given_name ?? "");
      setDraft(null);
      setOldMail(null);
      preview.reset();
      apply.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, guid]);

  function computeSuggestion(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!newSurname.trim()) return;
    preview.mutate(
      {
        new_surname: newSurname.trim(),
        ...(newGiven.trim() ? { new_given_name: newGiven.trim() } : {}),
      },
      {
        onSuccess: (out) => {
          setDraft({
            given_name: out.given_name ?? "",
            surname: out.surname,
            display_name: out.display_name,
            upn: out.upn ?? "",
            mail: out.mail ?? "",
            sam_account_name: out.sam_account_name ?? "",
            keep_old_mail_as_alias: true,
          });
          setOldMail(out.old_mail_kept_as_alias);
        },
      },
    );
  }

  function setDraftField<K extends keyof Draft>(key: K, value: Draft[K]): void {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    apply.reset();
  }

  function submitRename(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!draft) return;
    const body: RenameApplyRequest = {
      given_name: draft.given_name.trim() || null,
      surname: draft.surname.trim() || null,
      display_name: draft.display_name.trim() || null,
      mail: draft.mail.trim() || null,
      keep_old_mail_as_alias: draft.keep_old_mail_as_alias,
    };
    if (canChangeLogin) {
      body.upn = draft.upn.trim() || null;
      body.sam_account_name = draft.sam_account_name.trim() || null;
    }
    apply.mutate(body, { onSuccess: () => onClose() });
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
          <DialogTitle>{t("rename.title")}</DialogTitle>
          <DialogDescription>{user ? displayLabel(user) : ""}</DialogDescription>
        </DialogHeader>

        {draft === null ? (
          <form onSubmit={computeSuggestion} className="space-y-4">
            <p className="text-sm text-muted-foreground">{t("rename.subtitle")}</p>
            {preview.isError ? (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t(errorKey(preview.error))}
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="rename-surname">{t("rename.new_surname")}</Label>
              <Input
                id="rename-surname"
                value={newSurname}
                onChange={(e) => setNewSurname(e.target.value)}
                maxLength={200}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rename-given">{t("rename.new_given_name")}</Label>
              <Input
                id="rename-given"
                value={newGiven}
                onChange={(e) => setNewGiven(e.target.value)}
                maxLength={200}
                placeholder={t("rename.new_given_name_hint")}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={preview.isPending || !newSurname.trim()}>
                {preview.isPending ? t("rename.computing") : t("rename.compute")}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <form onSubmit={submitRename} className="space-y-4">
            <p className="text-sm text-muted-foreground">{t("rename.review_title")}</p>
            {apply.isError ? (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t(errorKey(apply.error))}
              </div>
            ) : null}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <DraftField
                id="r-given"
                label={t("rename.field_given")}
                value={draft.given_name}
                onChange={(v) => setDraftField("given_name", v)}
              />
              <DraftField
                id="r-surname"
                label={t("rename.field_surname")}
                value={draft.surname}
                onChange={(v) => setDraftField("surname", v)}
              />
            </div>
            <DraftField
              id="r-display"
              label={t("rename.field_display_name")}
              value={draft.display_name}
              onChange={(v) => setDraftField("display_name", v)}
            />
            <DraftField
              id="r-mail"
              label={t("rename.field_mail")}
              value={draft.mail}
              onChange={(v) => setDraftField("mail", v)}
            />
            {canChangeLogin ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <DraftField
                  id="r-upn"
                  label={t("rename.field_upn")}
                  value={draft.upn}
                  onChange={(v) => setDraftField("upn", v)}
                />
                <DraftField
                  id="r-sam"
                  label={t("rename.field_sam")}
                  value={draft.sam_account_name}
                  onChange={(v) => setDraftField("sam_account_name", v)}
                />
              </div>
            ) : null}

            {oldMail ? (
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={draft.keep_old_mail_as_alias}
                  onChange={(e) => setDraftField("keep_old_mail_as_alias", e.target.checked)}
                />
                <span>{t("rename.keep_old_alias", { mail: oldMail })}</span>
              </label>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDraft(null)}>
                {t("rename.back")}
              </Button>
              <Button type="submit" disabled={apply.isPending}>
                {apply.isPending ? t("rename.applying") : t("rename.apply")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DraftField(props: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
}): JSX.Element {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={props.id}>{props.label}</Label>
      <Input id={props.id} value={props.value} onChange={(e) => props.onChange(e.target.value)} />
    </div>
  );
}
