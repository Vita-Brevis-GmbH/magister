import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useBulkUserAction,
  useCurrentUser,
  useUsers,
  type BulkUserAction,
  type UseUsersParams,
} from "@/api/hooks";
import type { AdUserOut } from "@/api/types";
import { ResetPasswordModal, type ResetTarget } from "@/components/ResetPasswordModal";
import { SkeletonRow } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { UserAvatar } from "@/components/UserAvatar";
import { UserStatusModal } from "@/components/UserStatusModal";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useFormatters } from "@/lib/useFormatters";
import { cn } from "@/lib/utils";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/users")({
  component: UsersPage,
});

type KindFilter = "all" | "teacher" | "student";

function UsersPage(): JSX.Element {
  // /users/$guid is a child route; hand off when one is active.
  const childMatches = useChildMatches();
  const { t } = useTranslation();
  const fmt = useFormatters();
  const [kind, setKind] = useState<KindFilter>("all");
  const [search, setSearch] = useState("");
  const [resetTarget, setResetTarget] = useState<ResetTarget | null>(null);
  const [statusTarget, setStatusTarget] = useState<AdUserOut | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [attrsOpen, setAttrsOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [bulkResult, setBulkResult] = useState<{ ok: number; failed: number } | null>(null);
  const me = useCurrentUser();
  const bulk = useBulkUserAction();
  const canEditUsers = me.data?.is_admin || (me.data?.roles ?? []).includes("smi");
  const isAdmin = me.data?.is_admin ?? false;
  // Listing is scoped to the caller's school(s); anyone who sees the list
  // is also allowed to toggle status of users in it (Admin / Schulleitung /
  // SMI — backend enforces the final gate via require_user_lifecycle_writer).
  // We hide the action for the caller's own row to avoid the 400 self-disable.
  const canToggleStatus = (u: AdUserOut): boolean =>
    !!me.data && u.ad_object_guid !== me.data.ad_object_guid;

  const params: UseUsersParams = {
    limit: 50,
    ...(kind !== "all" && { kind }),
    ...(search && { search }),
  };
  const q = useUsers(params);

  const items = q.data?.items ?? [];
  const selectableGuids = items.map((u) => u.ad_object_guid);
  const allSelected = selectableGuids.length > 0 && selectableGuids.every((g) => selected.has(g));

  function toggle(guid: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(guid)) next.delete(guid);
      else next.add(guid);
      return next;
    });
    setBulkResult(null);
  }

  function toggleAll(): void {
    setSelected(allSelected ? new Set() : new Set(selectableGuids));
    setBulkResult(null);
  }

  function clearSelection(): void {
    setSelected(new Set());
    setConfirmBulkDelete(false);
    setBulkResult(null);
  }

  function runBulk(action: BulkUserAction): void {
    const guids = [...selected];
    if (guids.length === 0) return;
    bulk.mutate(
      { guids, action },
      {
        onSuccess: (res) => {
          setBulkResult({ ok: res.ok.length, failed: res.failed.length });
          setSelected(new Set(res.failed.map((f) => f.guid)));
          setConfirmBulkDelete(false);
          setAttrsOpen(false);
        },
      },
    );
  }

  if (childMatches.length > 0) return <Outlet />;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("users.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("users.intro")}</p>
        </div>
        <div className="flex items-center gap-3">
          <p className="text-xs text-muted-foreground">
            {t("users.last_sync_at")}:{" "}
            <span className="font-medium text-foreground">
              {q.data?.last_sync_at
                ? fmt.formatDateTime(q.data.last_sync_at)
                : t("users.never_synced")}
            </span>
          </p>
          {me.data?.is_admin ? (
            <Link
              to="/admin/user-new"
              className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {t("users.new_user")}
            </Link>
          ) : null}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" className="inline-flex rounded-md border bg-card p-0.5">
          {(["all", "teacher", "student"] as const).map((k) => (
            <button
              key={k}
              role="tab"
              aria-selected={kind === k}
              onClick={() => setKind(k)}
              className={cn(
                "rounded px-3 py-1.5 text-sm font-medium transition-colors",
                kind === k
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`users.filter_kind_${k}`)}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder={t("users.search_placeholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 min-w-[16rem] flex-1 rounded-md border border-input bg-background px-3 text-sm"
        />
      </div>

      {canEditUsers && selected.size > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border bg-accent/40 px-3 py-2 text-sm">
          <span className="font-medium">{t("users.bulk.selected", { count: selected.size })}</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={bulk.isPending}
            onClick={() => runBulk({ type: "disable" })}
          >
            {t("user_status.button_disable")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={bulk.isPending}
            onClick={() => runBulk({ type: "enable" })}
          >
            {t("user_status.button_enable")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={bulk.isPending}
            onClick={() => setAttrsOpen(true)}
          >
            {t("users.bulk.attrs_button")}
          </Button>
          {isAdmin ? (
            confirmBulkDelete ? (
              <span className="flex items-center gap-2">
                <span className="text-destructive">{t("users.bulk.delete_confirm")}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  disabled={bulk.isPending}
                  onClick={() => runBulk({ type: "delete" })}
                >
                  {t("users.detail.delete_yes")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmBulkDelete(false)}
                >
                  {t("common.cancel")}
                </Button>
              </span>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={bulk.isPending}
                onClick={() => setConfirmBulkDelete(true)}
              >
                {t("users.detail.delete")}
              </Button>
            )
          ) : null}
          <Button type="button" size="sm" variant="ghost" onClick={clearSelection}>
            {t("users.bulk.clear")}
          </Button>
          {bulk.isPending ? (
            <span className="text-muted-foreground">{t("common.loading")}</span>
          ) : null}
        </div>
      ) : null}

      {bulkResult ? (
        <p className="rounded-md border bg-card px-3 py-2 text-sm">
          {t("users.bulk.result", { ok: bulkResult.ok, failed: bulkResult.failed })}
        </p>
      ) : null}

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : !q.isLoading && q.data && q.data.items.length === 0 ? (
        <EmptyState message={t("users.empty")} />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                {canEditUsers ? (
                  <TableHead className="w-10">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      aria-label={t("users.bulk.select_all")}
                      className="h-4 w-4 rounded border-input"
                    />
                  </TableHead>
                ) : null}
                <TableHead>{t("users.name")}</TableHead>
                <TableHead>{t("users.kind")}</TableHead>
                <TableHead>{t("users.status")}</TableHead>
                <TableHead className="text-right">{t("users.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <SkeletonRow key={i} columns={canEditUsers ? 5 : 4} />
                  ))
                : q.data?.items.map((u) => (
                    <TableRow key={u.ad_object_guid}>
                      {canEditUsers ? (
                        <TableCell className="w-10">
                          <input
                            type="checkbox"
                            checked={selected.has(u.ad_object_guid)}
                            onChange={() => toggle(u.ad_object_guid)}
                            aria-label={t("users.bulk.select_one")}
                            className="h-4 w-4 rounded border-input"
                          />
                        </TableCell>
                      ) : null}
                      <TableCell>
                        <Link
                          to={canEditUsers ? "/users/$guid" : "/users"}
                          params={canEditUsers ? { guid: u.ad_object_guid } : undefined}
                          className="group flex items-center gap-3"
                        >
                          <UserAvatar user={u} size="md" />
                          <span className="flex flex-col leading-tight">
                            <span
                              className={cn(
                                "font-medium text-foreground",
                                canEditUsers && "group-hover:underline",
                              )}
                            >
                              {displayLabel(u)}
                            </span>
                            <span className="text-xs text-muted-foreground">{u.upn}</span>
                          </span>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <KindPill kind={u.kind} />
                      </TableCell>
                      <TableCell>
                        {u.enabled ? (
                          <StatusPill tone="ok">{t("users.status_active")}</StatusPill>
                        ) : (
                          <StatusPill tone="muted">{t("users.status_disabled")}</StatusPill>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {u.enabled &&
                          (u.kind === "student" || (u.kind === "teacher" && canEditUsers)) ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                setResetTarget({
                                  ad_object_guid: u.ad_object_guid,
                                  given_name: u.given_name,
                                  surname: u.surname,
                                  upn: u.upn,
                                  kind: u.kind === "teacher" ? "teacher" : "student",
                                })
                              }
                            >
                              {t("password_reset.button")}
                            </Button>
                          ) : null}
                          {canToggleStatus(u) ? (
                            <Button
                              type="button"
                              variant={u.enabled ? "outline" : "default"}
                              size="sm"
                              onClick={() => setStatusTarget(u)}
                            >
                              {u.enabled
                                ? t("user_status.button_disable")
                                : t("user_status.button_enable")}
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ResetPasswordModal student={resetTarget} onClose={() => setResetTarget(null)} />
      <UserStatusModal user={statusTarget} onClose={() => setStatusTarget(null)} />
      <BulkAttrsModal
        open={attrsOpen}
        count={selected.size}
        busy={bulk.isPending}
        onClose={() => setAttrsOpen(false)}
        onApply={(payload) => runBulk({ type: "attrs", payload })}
      />
    </div>
  );
}

type TriState = "keep" | "yes" | "no";

function triToValue(s: TriState): boolean | undefined {
  if (s === "yes") return true;
  if (s === "no") return false;
  return undefined;
}

function BulkAttrsModal({
  open,
  count,
  busy,
  onClose,
  onApply,
}: {
  open: boolean;
  count: number;
  busy: boolean;
  onClose: () => void;
  onApply: (payload: { cannot_change_password?: boolean; password_never_expires?: boolean }) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [cannot, setCannot] = useState<TriState>("keep");
  const [neverExp, setNeverExp] = useState<TriState>("keep");

  function apply(): void {
    const payload: { cannot_change_password?: boolean; password_never_expires?: boolean } = {};
    const c = triToValue(cannot);
    const n = triToValue(neverExp);
    if (c !== undefined) payload.cannot_change_password = c;
    if (n !== undefined) payload.password_never_expires = n;
    onApply(payload);
  }

  const nothingChosen = cannot === "keep" && neverExp === "keep";

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("users.bulk.attrs_title")}</DialogTitle>
          <DialogDescription>{t("users.bulk.attrs_desc", { count })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <TriField
            label={t("users.field.cannot_change_password")}
            value={cannot}
            onChange={setCannot}
          />
          <TriField
            label={t("users.field.password_never_expires")}
            value={neverExp}
            onChange={setNeverExp}
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="button" onClick={apply} disabled={busy || nothingChosen}>
            {busy ? t("common.loading") : t("users.bulk.attrs_apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TriField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: TriState;
  onChange: (v: TriState) => void;
}): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm">{label}</span>
      <div role="tablist" className="inline-flex rounded-md border bg-card p-0.5">
        {(["keep", "yes", "no"] as const).map((k) => (
          <button
            key={k}
            type="button"
            aria-selected={value === k}
            onClick={() => onChange(k)}
            className={cn(
              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
              value === k
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`users.bulk.tri_${k}`)}
          </button>
        ))}
      </div>
    </div>
  );
}

function KindPill({ kind }: { kind: AdUserOut["kind"] }): JSX.Element {
  const { t } = useTranslation();
  if (kind === "teacher") return <StatusPill tone="muted">{t("users.kind_teacher")}</StatusPill>;
  if (kind === "student") return <StatusPill tone="muted">{t("users.kind_student")}</StatusPill>;
  return <StatusPill tone="muted">{t("users.kind_admin")}</StatusPill>;
}

function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
