import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { usePasswordExpiry } from "@/api/hooks";
import type { PasswordExpiryRow, PasswordExpiryView } from "@/api/types";
import { SkeletonRow } from "@/components/Skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UsersSubNav } from "@/components/UsersSubNav";
import { gradeLabel } from "@/lib/grade";
import { useFormatters } from "@/lib/useFormatters";
import { userLabel } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/password-expiry")({
  component: PasswordExpiryPage,
});

const DAY_CHOICES = [7, 14, 30, 60];

export function PasswordExpiryPage(): JSX.Element {
  const { t } = useTranslation();
  const fmt = useFormatters();
  const [view, setView] = useState<PasswordExpiryView>("expiring");
  const [days, setDays] = useState(14);
  const q = usePasswordExpiry(view, days);
  const rows = q.data?.rows ?? [];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <UsersSubNav />
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">
            {t("password_expiry.title")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("password_expiry.intro")}</p>
        </div>
      </header>

      {q.data && !q.data.info_as_of ? (
        <Notice tone="warn">{t("password_expiry.no_info")}</Notice>
      ) : null}
      {q.data && q.data.info_as_of && !(q.data.notice_enabled && q.data.mail_ready) ? (
        <Notice tone="warn">
          {q.data.notice_enabled
            ? t("password_expiry.mail_not_ready")
            : t("password_expiry.notice_off")}
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" className="inline-flex rounded-md border bg-background p-0.5">
          {(["expiring", "no_mail"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={
                view === v
                  ? "rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
                  : "rounded px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
              }
            >
              {t(`password_expiry.view_${v}`)}
            </button>
          ))}
        </div>
        {view === "expiring" ? (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{t("password_expiry.within")}</span>
            <select
              aria-label={t("password_expiry.within")}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              {DAY_CHOICES.map((d) => (
                <option key={d} value={d}>
                  {t("password_expiry.days", { count: d })}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {q.data ? (
          <p className="text-sm text-muted-foreground">
            {t("password_expiry.count", { count: rows.length })}
          </p>
        ) : null}
      </div>

      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("password_expiry.col_name")}</TableHead>
              <TableHead>{t("password_expiry.col_zielgruppe")}</TableHead>
              <TableHead>{t("password_expiry.col_expires")}</TableHead>
              <TableHead>{t("password_expiry.col_mail")}</TableHead>
              <TableHead>{t("password_expiry.col_notice")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={5} />)
            ) : q.isError ? (
              <TableRow>
                <TableCell colSpan={5} className="py-6 text-center text-sm text-destructive">
                  {t("errors.generic")}
                </TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  {t(`password_expiry.empty_${view}`)}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.ad_object_guid}>
                  <TableCell>
                    <div className="flex flex-col leading-tight">
                      <span className="font-medium">{userLabel(row)}</span>
                      <span className="text-xs text-muted-foreground">{row.upn}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">
                    {row.group_template_name ?? "—"}
                    {row.jahrgangsstufe !== null ? (
                      <span className="ml-1 text-xs text-muted-foreground">
                        · {t("password_expiry.grade", { grade: gradeLabel(row.jahrgangsstufe) })}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm">
                    <ExpiryCell row={row} formatDate={fmt.formatDate} />
                  </TableCell>
                  <TableCell className="text-sm">
                    {row.mail ?? (
                      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
                        {t("password_expiry.no_mail")}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {row.notice_status
                      ? t(`password_expiry.notice_${row.notice_status}`, {
                          date: row.notice_at ? fmt.formatDate(row.notice_at) : "",
                          days: row.notice_threshold_days ?? "",
                        })
                      : "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function ExpiryCell({
  row,
  formatDate,
}: {
  row: PasswordExpiryRow;
  formatDate: (iso: string | null | undefined) => string;
}): JSX.Element {
  const { t } = useTranslation();
  if (!row.password_expires_at || row.days_left === null) {
    return <span className="text-muted-foreground">{t("password_expiry.never")}</span>;
  }
  const expired = row.days_left <= 0;
  return (
    <span className="flex flex-col leading-tight">
      <span>{formatDate(row.password_expires_at)}</span>
      <span
        className={cn(
          "text-xs",
          expired ? "font-medium text-destructive" : row.days_left <= 3 ? "text-amber-600" : "",
          !expired && row.days_left > 3 && "text-muted-foreground",
        )}
      >
        {expired
          ? t("password_expiry.expired")
          : t("password_expiry.in_days", { count: row.days_left })}
      </span>
    </span>
  );
}

function Notice({ children, tone }: { children: React.ReactNode; tone: "warn" }): JSX.Element {
  return (
    <p
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        tone === "warn" && "border-amber-500/50 bg-amber-500/10",
      )}
    >
      {children}
    </p>
  );
}
