import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useRevokeSubstitution, useSubstitutions } from "@/api/hooks";
import type { SubstitutionOut } from "@/api/types";
import { SkeletonRow } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
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

export const Route = createFileRoute("/_app/admin/substitutions")({
  component: SubstitutionsPage,
});

type StatusFilter = "active" | "expiring" | "all";

const EXPIRING_DAYS = 14;

function SubstitutionsPage(): JSX.Element {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<StatusFilter>("active");
  const q = useSubstitutions();
  const revoke = useRevokeSubstitution();
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const now = new Date();
  const soonMs = EXPIRING_DAYS * 24 * 60 * 60 * 1000;

  function getStatus(sub: SubstitutionOut): "active" | "expiring" | "expired" {
    const validTo = sub.valid_to ? new Date(sub.valid_to) : null;
    if (validTo && validTo <= now) return "expired";
    if (validTo && validTo.getTime() - now.getTime() <= soonMs) return "expiring";
    return "active";
  }

  const filtered = (q.data ?? []).filter((sub) => {
    if (filter === "all") return true;
    const s = getStatus(sub);
    if (filter === "active") return s === "active" || s === "expiring";
    if (filter === "expiring") return s === "expiring";
    return true;
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          {t("substitutions.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("substitutions.intro")}</p>
      </header>

      <div className="flex items-center gap-2">
        <div role="tablist" className="inline-flex rounded-md border bg-card p-0.5">
          {(["active", "expiring", "all"] as const).map((f) => (
            <button
              key={f}
              role="tab"
              aria-selected={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                "rounded px-3 py-1.5 text-sm font-medium transition-colors",
                filter === f
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`substitutions.filter_${f}`)}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {!q.isLoading && t("substitutions.count", { count: filtered.length })}
        </p>
      </div>

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : !q.isLoading && filtered.length === 0 ? (
        <EmptyState message={t("substitutions.empty")} />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("substitutions.col_teacher")}</TableHead>
                <TableHead>{t("substitutions.col_class")}</TableHead>
                <TableHead>{t("substitutions.col_valid_from")}</TableHead>
                <TableHead>{t("substitutions.col_valid_to")}</TableHead>
                <TableHead>{t("substitutions.col_status")}</TableHead>
                <TableHead className="w-0 text-right">{t("users.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.isLoading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} columns={6} />)
                : filtered.map((sub) => (
                    <SubstitutionRow
                      key={sub.id}
                      sub={sub}
                      status={getStatus(sub)}
                      revoking={revoke.isPending && confirmId === sub.id}
                      confirming={confirmId === sub.id}
                      onRevokeClick={() => setConfirmId(sub.id)}
                      onRevokeConfirm={() => {
                        revoke.mutate(sub.id, { onSuccess: () => setConfirmId(null) });
                      }}
                      onRevokeCancel={() => setConfirmId(null)}
                    />
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {t("substitutions.create_hint")}{" "}
        <Link to="/classes" className="text-primary hover:underline">
          {t("nav.classes")}
        </Link>
      </p>
    </div>
  );
}

function SubstitutionRow({
  sub,
  status,
  revoking,
  confirming,
  onRevokeClick,
  onRevokeConfirm,
  onRevokeCancel,
}: {
  sub: SubstitutionOut;
  status: "active" | "expiring" | "expired";
  revoking: boolean;
  confirming: boolean;
  onRevokeClick: () => void;
  onRevokeConfirm: () => void;
  onRevokeCancel: () => void;
}): JSX.Element {
  const { t } = useTranslation();

  const upn = sub.upn ?? "";
  const teacher = { ...sub, upn };

  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col leading-tight">
          <span className="font-medium">{displayLabel(teacher)}</span>
          {upn && <span className="text-xs text-muted-foreground">{upn}</span>}
        </div>
      </TableCell>
      <TableCell>
        <Link
          to="/classes/$classId"
          params={{ classId: String(sub.class_id) }}
          className="hover:underline"
        >
          {sub.class_name}
        </Link>
      </TableCell>
      <TableCell className="text-sm">{sub.valid_from.slice(0, 10)}</TableCell>
      <TableCell className="text-sm">
        {sub.valid_to ? sub.valid_to.slice(0, 10) : <span className="text-muted-foreground">—</span>}
      </TableCell>
      <TableCell>
        {status === "expired" ? (
          <StatusPill tone="muted">{t("substitutions.status_expired")}</StatusPill>
        ) : status === "expiring" ? (
          <StatusPill tone="warn">{t("substitutions.status_expiring")}</StatusPill>
        ) : (
          <StatusPill tone="ok">{t("substitutions.status_active")}</StatusPill>
        )}
      </TableCell>
      <TableCell className="text-right">
        {confirming ? (
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={revoking}
              onClick={onRevokeConfirm}
            >
              {revoking ? t("common.loading") : t("substitutions.revoke_confirm")}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={onRevokeCancel}>
              {t("common.cancel")}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={status === "expired"}
            onClick={onRevokeClick}
          >
            {t("substitutions.revoke_button")}
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
