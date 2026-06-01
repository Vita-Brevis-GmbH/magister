import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuditEvents, type UseAuditEventsParams } from "@/api/hooks";
import type { AuditEventOut } from "@/api/types";
import { SkeletonRow } from "@/components/Skeleton";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_app/admin/audit")({
  component: AuditPage,
});

const PAGE_SIZE = 50;

function AuditPage(): JSX.Element {
  const { t } = useTranslation();
  const [actorUpn, setActorUpn] = useState("");
  const [action, setAction] = useState("");
  const [targetKind, setTargetKind] = useState("");
  const [fromTs, setFromTs] = useState("");
  const [toTs, setToTs] = useState("");
  const [offset, setOffset] = useState(0);

  const params: UseAuditEventsParams = {
    limit: PAGE_SIZE,
    offset,
    ...(actorUpn && { actor_upn: actorUpn }),
    ...(action && { action }),
    ...(targetKind && { target_kind: targetKind }),
    ...(fromTs && { from_ts: new Date(fromTs).toISOString() }),
    ...(toTs && { to_ts: new Date(toTs).toISOString() }),
  };

  const q = useAuditEvents(params);

  const resetFilters = () => {
    setActorUpn("");
    setAction("");
    setTargetKind("");
    setFromTs("");
    setToTs("");
    setOffset(0);
  };

  const totalPages = q.data ? Math.ceil(q.data.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("audit.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("audit.intro")}</p>
      </header>

      <div className="flex flex-wrap items-end gap-3 rounded-md border bg-card px-4 py-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">{t("audit.actor_upn")}</span>
          <input
            type="search"
            value={actorUpn}
            onChange={(e) => {
              setActorUpn(e.target.value);
              setOffset(0);
            }}
            placeholder={t("audit.actor_upn_placeholder")}
            className="h-8 w-48 rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">{t("audit.action")}</span>
          <input
            type="search"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
            placeholder={t("audit.action_placeholder")}
            className="h-8 w-44 rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            {t("audit.target_kind")}
          </span>
          <input
            type="search"
            value={targetKind}
            onChange={(e) => {
              setTargetKind(e.target.value);
              setOffset(0);
            }}
            placeholder={t("audit.target_kind_placeholder")}
            className="h-8 w-36 rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">{t("audit.from_ts")}</span>
          <input
            type="date"
            value={fromTs}
            onChange={(e) => {
              setFromTs(e.target.value);
              setOffset(0);
            }}
            className="h-8 rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">{t("audit.to_ts")}</span>
          <input
            type="date"
            value={toTs}
            onChange={(e) => {
              setToTs(e.target.value);
              setOffset(0);
            }}
            className="h-8 rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <Button variant="ghost" size="sm" onClick={resetFilters}>
          {t("audit.reset_filters")}
        </Button>
      </div>

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : !q.isLoading && q.data && q.data.items.length === 0 ? (
        <EmptyState message={t("audit.empty")} />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("audit.col_timestamp")}</TableHead>
                <TableHead>{t("audit.col_actor")}</TableHead>
                <TableHead>{t("audit.col_action")}</TableHead>
                <TableHead>{t("audit.col_target")}</TableHead>
                <TableHead>{t("audit.col_ip")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.isLoading
                ? Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} columns={5} />)
                : q.data?.items.map((ev) => <AuditRow key={ev.id} event={ev} />)}
            </TableBody>
          </Table>
        </div>
      )}

      {q.data && q.data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {t("audit.pagination_info", {
              page: currentPage,
              total: totalPages,
              count: q.data.total,
            })}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t("audit.prev")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= q.data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              {t("audit.next")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function AuditRow({ event: ev }: { event: AuditEventOut }): JSX.Element {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <TableRow className="cursor-pointer" onClick={() => setExpanded((x) => !x)}>
        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
          {new Date(ev.ts).toLocaleString()}
        </TableCell>
        <TableCell className="max-w-[14rem] truncate text-sm">
          {ev.actor_upn ?? <span className="text-muted-foreground">—</span>}
        </TableCell>
        <TableCell>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{ev.action}</code>
        </TableCell>
        <TableCell className="text-sm">
          <span className="text-muted-foreground">{ev.target_kind}/</span>
          {ev.target_id}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">{ev.ip ?? "—"}</TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={5} className="bg-muted/40 px-4 py-3">
            <pre className="overflow-x-auto whitespace-pre-wrap text-xs">
              {JSON.stringify(ev.payload, null, 2)}
            </pre>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
