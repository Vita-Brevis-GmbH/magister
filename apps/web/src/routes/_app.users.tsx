import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useCurrentUser, useUsers, type UseUsersParams } from "@/api/hooks";
import type { AdUserOut } from "@/api/types";
import { ResetPasswordModal } from "@/components/ResetPasswordModal";
import { SkeletonRow } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  const [kind, setKind] = useState<KindFilter>("all");
  const [search, setSearch] = useState("");
  const [resetTarget, setResetTarget] = useState<AdUserOut | null>(null);
  const me = useCurrentUser();
  const canEditUsers =
    me.data?.is_admin || (me.data?.roles ?? []).includes("smi");

  const params: UseUsersParams = {
    limit: 50,
    ...(kind !== "all" && { kind }),
    ...(search && { search }),
  };
  const q = useUsers(params);

  if (childMatches.length > 0) return <Outlet />;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">
            {t("users.title")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("users.intro")}</p>
        </div>
        <p className="text-xs text-muted-foreground">
          {t("users.last_sync_at")}:{" "}
          <span className="font-medium text-foreground">
            {q.data?.last_sync_at
              ? new Date(q.data.last_sync_at).toLocaleString()
              : t("users.never_synced")}
          </span>
        </p>
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
                <TableHead>{t("users.name")}</TableHead>
                <TableHead>{t("users.kind")}</TableHead>
                <TableHead>{t("users.status")}</TableHead>
                <TableHead className="text-right">{t("users.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.isLoading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} columns={4} />)
                : q.data?.items.map((u) => (
                    <TableRow key={u.ad_object_guid}>
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
                        {u.kind === "student" && u.enabled ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => setResetTarget(u)}
                          >
                            {t("password_reset.button")}
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ResetPasswordModal student={resetTarget} onClose={() => setResetTarget(null)} />
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
