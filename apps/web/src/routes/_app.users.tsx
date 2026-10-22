import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useBulkUserAction,
  useCurrentUser,
  useInstanceProfile,
  useUsers,
  type BulkUserAction,
  type UseUsersParams,
  type UserSortKey,
} from "@/api/hooks";
import type { AdUserOut } from "@/api/types";
import { ResetPasswordModal, type ResetTarget } from "@/components/ResetPasswordModal";
import { SkeletonRow } from "@/components/Skeleton";
import { SortableHead } from "@/components/SortableHead";
import { UsersSubNav } from "@/components/UsersSubNav";
import { StatusPill } from "@/components/StatusPill";
import { UserAvatar } from "@/components/UserAvatar";
import { UserStatusModal } from "@/components/UserStatusModal";
import { ZielgruppeAssign } from "@/components/ZielgruppeAssign";
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
import { gradeLabel } from "@/lib/grade";
import { useFormatters } from "@/lib/useFormatters";
import type { SortState } from "@/lib/useSortable";
import { cn } from "@/lib/utils";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/users")({
  component: UsersPage,
});

type KindFilter = "all" | "teacher" | "student";
type StatusFilter = "all" | "active" | "disabled" | "missing";
type PolicyFilter = "" | "cannot_change" | "never_expires" | "stored";

// Jahrgänge für den Filter: -1 = KG1, 0 = KG2, dann 1..13.
const GRADES = Array.from({ length: 15 }, (_, i) => i - 1);

const filterSelect =
  "h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground";

export function UsersPage(): JSX.Element {
  // /users/$guid is a child route; hand off when one is active.
  const childMatches = useChildMatches();
  const { t } = useTranslation();
  const fmt = useFormatters();
  const [kind, setKind] = useState<KindFilter>("all");
  // In the company profile there is no student/teacher split — every account is
  // just a "Benutzer", so the kind filter + kind column collapse to that.
  const isCompany = (useInstanceProfile().data ?? "school") === "company";
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [grade, setGrade] = useState("");
  const [zielgruppe, setZielgruppe] = useState("");
  const [policy, setPolicy] = useState<PolicyFilter>("");
  // Sortiert wird im Server: die Liste ist seitenweise.
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const [resetTarget, setResetTarget] = useState<ResetTarget | null>(null);
  const [statusTarget, setStatusTarget] = useState<AdUserOut | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [attrsOpen, setAttrsOpen] = useState(false);
  const [zielgruppeOpen, setZielgruppeOpen] = useState(false);
  // Die Konten, für die "Zielgruppe zuordnen" geöffnet wurde — fest, damit das
  // Ergebnis stehen bleibt, auch wenn die Auswahl danach geleert wird.
  const [zielgruppeGuids, setZielgruppeGuids] = useState<string[]>([]);
  const [zielgruppeSchool, setZielgruppeSchool] = useState<number | undefined>(undefined);
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

  const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
  const params: UseUsersParams = {
    limit: pageSize,
    offset,
    ...(kind !== "all" && { kind }),
    ...(search && { search }),
    ...(status === "active" && { enabled: true, missing: false }),
    ...(status === "disabled" && { enabled: false }),
    ...(status === "missing" && { missing: true }),
    ...(grade !== "" && { jahrgangsstufe: Number(grade) }),
    ...(zielgruppe !== "" && { group_template_id: Number(zielgruppe) }),
    ...(policy && { policy }),
    sort: sort.key as UserSortKey,
    dir: sort.dir,
  };
  const q = useUsers(params);

  // Selection is per-page: any navigation or filter change clears it so a
  // bulk action can never touch users the operator can't currently see.
  function resetPaging(): void {
    setOffset(0);
    setSelected(new Set());
    setBulkResult(null);
    setConfirmBulkDelete(false);
  }
  function changeKind(k: KindFilter): void {
    setKind(k);
    resetPaging();
  }
  function changeSearch(v: string): void {
    setSearch(v);
    resetPaging();
  }
  function changeFilter<T>(set: (v: T) => void, v: T): void {
    set(v);
    resetPaging();
  }
  function toggleSort(key: string): void {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );
    resetPaging();
  }
  function goToOffset(next: number): void {
    setOffset(next);
    setSelected(new Set());
    setBulkResult(null);
    setConfirmBulkDelete(false);
  }
  function changePageSize(n: number): void {
    setPageSize(n);
    resetPaging();
  }

  const total = q.data?.total ?? 0;
  const page = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasPrev = offset > 0;
  const hasNext = offset + pageSize < total;

  const items = q.data?.items ?? [];
  const selectableGuids = items.map((u) => u.ad_object_guid);
  const allSelected = selectableGuids.length > 0 && selectableGuids.every((g) => selected.has(g));
  // Ausgewählt zählt nur, was angezeigt wird: eine Sammelaktion darf nie ein
  // Konto treffen, das ein Filter oder eine Änderung aus der Ansicht genommen
  // hat. Permanent delete is step 2 — only offered when every selected
  // account is already deactivated.
  const selectedUsers = items.filter((u) => selected.has(u.ad_object_guid));
  const visibleSelected = selectedUsers.map((u) => u.ad_object_guid);

  // Verschwindet eine Zeile aus der Ansicht (Filter, neu geladene Liste nach
  // einer Aktion), verschwindet sie auch aus der Auswahl.
  useEffect(() => {
    const shown = new Set((q.data?.items ?? []).map((u) => u.ad_object_guid));
    setSelected((prev) => {
      const kept = [...prev].filter((g) => shown.has(g));
      return kept.length === prev.size ? prev : new Set(kept);
    });
  }, [q.data]);
  const allSelectedDisabled = selectedUsers.length > 0 && selectedUsers.every((u) => !u.enabled);

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
    setZielgruppeOpen(false);
    setConfirmBulkDelete(false);
    setBulkResult(null);
  }

  function runBulk(action: BulkUserAction): void {
    const guids = visibleSelected;
    if (guids.length === 0) return;
    bulk.mutate(
      { guids, action },
      {
        onSuccess: (res) => {
          setBulkResult({ ok: res.ok.length, failed: res.failed.length });
          // Nach der Aktion ist die Auswahl leer; was scheiterte, sagt die
          // Meldung darunter.
          setSelected(new Set());
          setZielgruppeOpen(false);
          setConfirmBulkDelete(false);
          setAttrsOpen(false);
        },
      },
    );
  }

  function openZielgruppe(): void {
    if (zielgruppeOpen) {
      setZielgruppeOpen(false);
      return;
    }
    setZielgruppeGuids(visibleSelected);
    setZielgruppeSchool(
      new Set(selectedUsers.map((u) => u.school_id)).size === 1
        ? (selectedUsers[0]?.school_id ?? undefined)
        : undefined,
    );
    setZielgruppeOpen(true);
    setBulkResult(null);
  }

  if (childMatches.length > 0) return <Outlet />;

  return (
    <div className="space-y-6">
      <UsersSubNav />
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
        {!isCompany ? (
          <div role="tablist" className="inline-flex rounded-md border bg-card p-0.5">
            {(["all", "teacher", "student"] as const).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                onClick={() => changeKind(k)}
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
        ) : null}
        <input
          type="search"
          placeholder={t("users.search_placeholder")}
          value={search}
          onChange={(e) => changeSearch(e.target.value)}
          className="h-9 min-w-[16rem] flex-1 rounded-md border border-input bg-background px-3 text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("users.filter_status")}
          className={filterSelect}
          value={status}
          onChange={(e) => changeFilter(setStatus, e.target.value as StatusFilter)}
        >
          <option value="all">{t("users.filter_status_all")}</option>
          <option value="active">{t("users.status_active")}</option>
          <option value="disabled">{t("users.status_disabled")}</option>
          <option value="missing">{t("users.filter_missing")}</option>
        </select>
        {!isCompany ? (
          <select
            aria-label={t("users.filter_grade")}
            className={filterSelect}
            value={grade}
            onChange={(e) => changeFilter(setGrade, e.target.value)}
          >
            <option value="">{t("users.filter_grade_all")}</option>
            {GRADES.map((g) => (
              <option key={g} value={String(g)}>
                {gradeLabel(g)}
              </option>
            ))}
          </select>
        ) : null}
        <select
          aria-label={t("users.filter_zielgruppe")}
          className={filterSelect}
          value={zielgruppe}
          onChange={(e) => changeFilter(setZielgruppe, e.target.value)}
        >
          <option value="">{t("users.filter_zielgruppe_all")}</option>
          <option value="0">{t("users.filter_zielgruppe_none")}</option>
          {(q.data?.zielgruppen ?? []).map((z) => (
            <option key={z.id} value={String(z.id)}>
              {z.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t("users.filter_policy")}
          className={filterSelect}
          value={policy}
          onChange={(e) => changeFilter(setPolicy, e.target.value as PolicyFilter)}
        >
          <option value="">{t("users.filter_policy_all")}</option>
          <option value="cannot_change">{t("users.field.cannot_change_password")}</option>
          <option value="never_expires">{t("users.field.password_never_expires")}</option>
          <option value="stored">{t("users.policy_stored")}</option>
        </select>
      </div>

      {canEditUsers && visibleSelected.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border bg-accent/40 px-3 py-2 text-sm">
          <span className="font-medium">
            {t("users.bulk.selected", { count: visibleSelected.length })}
          </span>
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
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={bulk.isPending}
              onClick={openZielgruppe}
            >
              {t("zielgruppe_assign.bulk_button")}
            </Button>
          ) : null}
          {isAdmin && allSelectedDisabled ? (
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
                {t("users.detail.delete_permanent")}
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

      {isAdmin && zielgruppeOpen && zielgruppeGuids.length > 0 ? (
        <div className="space-y-2 rounded-md border bg-card p-3">
          <ZielgruppeAssign
            guids={zielgruppeGuids}
            // Nur wenn alle gewählten am selben Standort sind, nach ihm filtern.
            schoolId={zielgruppeSchool}
            // Nach dem Zuordnen ist die Auswahl leer; das Ergebnis bleibt hier stehen.
            onDone={() => setSelected(new Set())}
          />
          <Button type="button" size="sm" variant="ghost" onClick={() => setZielgruppeOpen(false)}>
            {t("common.close")}
          </Button>
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
                <SortableHead sortKey="name" sort={sort} onSort={toggleSort}>
                  {t("users.name")}
                </SortableHead>
                <SortableHead sortKey="kind" sort={sort} onSort={toggleSort}>
                  {t("users.kind")}
                </SortableHead>
                <SortableHead sortKey="status" sort={sort} onSort={toggleSort}>
                  {t("users.status")}
                </SortableHead>
                {!isCompany ? (
                  <SortableHead sortKey="jahrgangsstufe" sort={sort} onSort={toggleSort}>
                    {t("users.col_grade")}
                  </SortableHead>
                ) : null}
                <SortableHead sortKey="zielgruppe" sort={sort} onSort={toggleSort}>
                  {t("users.col_zielgruppe")}
                </SortableHead>
                <SortableHead sortKey="policy" sort={sort} onSort={toggleSort}>
                  {t("users.col_policy")}
                </SortableHead>
                <TableHead className="text-right">{t("users.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <SkeletonRow key={i} columns={(canEditUsers ? 8 : 7) - (isCompany ? 1 : 0)} />
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
                        <KindPill kind={u.kind} company={isCompany} />
                      </TableCell>
                      <TableCell>
                        {u.ad_missing_since ? (
                          <StatusPill tone="danger">{t("users.delete.badge")}</StatusPill>
                        ) : u.enabled ? (
                          <StatusPill tone="ok">{t("users.status_active")}</StatusPill>
                        ) : (
                          <StatusPill tone="muted">{t("users.status_disabled")}</StatusPill>
                        )}
                      </TableCell>
                      {!isCompany ? (
                        <TableCell className="text-sm">
                          {u.kind === "student" && u.jahrgangsstufe != null ? (
                            gradeLabel(u.jahrgangsstufe)
                          ) : (
                            <span className="text-xs text-muted-foreground">–</span>
                          )}
                        </TableCell>
                      ) : null}
                      <TableCell className="text-sm">
                        {u.group_template_name ?? (
                          <span className="text-xs text-muted-foreground">–</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <PolicyBadges user={u} />
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {u.enabled &&
                          (u.kind === "student" ||
                            ((u.kind === "teacher" || u.kind === "company") && canEditUsers)) ? (
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
                                  kind:
                                    u.kind === "teacher"
                                      ? "teacher"
                                      : u.kind === "company"
                                        ? "company"
                                        : "student",
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

      {!q.isLoading && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">
              {t("users.pagination_info", { page, total: totalPages, count: total })}
            </span>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              {t("users.per_page")}
              <select
                value={pageSize}
                onChange={(e) => changePageSize(Number(e.target.value))}
                className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              >
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!hasPrev || q.isFetching}
              onClick={() => goToOffset(Math.max(0, offset - pageSize))}
            >
              {t("users.pagination_prev")}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!hasNext || q.isFetching}
              onClick={() => goToOffset(offset + pageSize)}
            >
              {t("users.pagination_next")}
            </Button>
          </div>
        </div>
      ) : null}

      <ResetPasswordModal student={resetTarget} onClose={() => setResetTarget(null)} />
      <UserStatusModal user={statusTarget} onClose={() => setStatusTarget(null)} />
      <BulkAttrsModal
        open={attrsOpen}
        count={visibleSelected.length}
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
  onApply: (payload: {
    cannot_change_password?: boolean;
    password_never_expires?: boolean;
    store_password?: boolean;
  }) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [cannot, setCannot] = useState<TriState>("keep");
  const [neverExp, setNeverExp] = useState<TriState>("keep");
  const [store, setStore] = useState<TriState>("keep");

  function apply(): void {
    const payload: {
      cannot_change_password?: boolean;
      password_never_expires?: boolean;
      store_password?: boolean;
    } = {};
    const c = triToValue(cannot);
    const n = triToValue(neverExp);
    const s = triToValue(store);
    if (c !== undefined) payload.cannot_change_password = c;
    if (n !== undefined) payload.password_never_expires = n;
    if (s !== undefined) payload.store_password = s;
    onApply(payload);
  }

  const nothingChosen = cannot === "keep" && neverExp === "keep" && store === "keep";

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
          <TriField
            label={t("users.field.store_password")}
            value={store}
            onChange={(v) => {
              setStore(v);
              // Tresor nur bei festem Passwort: beide Schalter mit setzen.
              if (v === "yes") {
                setCannot("yes");
                setNeverExp("yes");
              }
            }}
          />
          <p className="text-xs text-muted-foreground">{t("users.bulk.store_hint")}</p>
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

function PolicyBadges({ user }: { user: AdUserOut }): JSX.Element {
  const { t } = useTranslation();
  if (!user.cannot_change_password && !user.password_never_expires && !user.store_password) {
    return <span className="text-xs text-muted-foreground">–</span>;
  }
  const badge = "rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground";
  return (
    <div className="flex flex-wrap gap-1">
      {user.cannot_change_password ? (
        <span className={badge} title={t("users.field.cannot_change_password")}>
          {t("users.policy_cannot_change_short")}
        </span>
      ) : null}
      {user.password_never_expires ? (
        <span className={badge} title={t("users.field.password_never_expires")}>
          {t("users.policy_never_expires_short")}
        </span>
      ) : null}
      {user.store_password ? (
        <span className={badge} title={t("users.policy_stored")}>
          {t("users.policy_stored_short")}
        </span>
      ) : null}
    </div>
  );
}

function KindPill({ kind, company }: { kind: AdUserOut["kind"]; company?: boolean }): JSX.Element {
  const { t } = useTranslation();
  // Company profile: teacher/student collapse to a generic "Benutzer"; admin
  // stays distinct.
  if (company && kind !== "admin")
    return <StatusPill tone="muted">{t("users.kind_user")}</StatusPill>;
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
