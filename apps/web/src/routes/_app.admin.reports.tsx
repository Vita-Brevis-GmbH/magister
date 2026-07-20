import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useActivityReport,
  useStudentsByClass,
  useStudentsBySchoolYear,
  useTeacherWorkload,
} from "@/api/hooks";
import { SkeletonRow } from "@/components/Skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { gradeLabel, gradeRangeLabel } from "@/lib/grade";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/admin/reports")({
  component: ReportsPage,
});

/** Full-width error row shown inside a report table when its query fails. */
function ErrorRow({ columns }: { columns: number }): JSX.Element {
  const { t } = useTranslation();
  return (
    <TableRow>
      <TableCell colSpan={columns} className="py-6 text-center text-sm text-destructive">
        {t("errors.generic")}
      </TableCell>
    </TableRow>
  );
}

function ReportsPage(): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("reports.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("reports.intro")}</p>
      </header>

      <StudentsByClassSection />
      <StudentsBySchoolYearSection />
      <TeacherWorkloadSection />
      <ActivitySection />
    </div>
  );
}

function StudentsBySchoolYearSection(): JSX.Element {
  const { t } = useTranslation();
  const q = useStudentsBySchoolYear();
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">{t("reports.school_year_title")}</h2>
        {q.data && (
          <p className="text-sm text-muted-foreground">
            {t("reports.school_year_total", { students: q.data.total_students })}
          </p>
        )}
      </div>
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("reports.col_school_year")}</TableHead>
              <TableHead className="text-right">{t("reports.col_students")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={2} />)
            ) : q.isError ? (
              <ErrorRow columns={2} />
            ) : (
              (q.data?.rows ?? []).map((row) => (
                <TableRow key={row.jahrgangsstufe ?? "unknown"}>
                  <TableCell className="font-medium">
                    {row.jahrgangsstufe === null
                      ? t("reports.school_year_unknown")
                      : gradeLabel(row.jahrgangsstufe)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.student_count}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function StudentsByClassSection(): JSX.Element {
  const { t } = useTranslation();
  const q = useStudentsByClass();
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">{t("reports.students_title")}</h2>
        {q.data && (
          <p className="text-sm text-muted-foreground">
            {t("reports.students_total", {
              students: q.data.total_students,
              classes: q.data.total_classes,
            })}
          </p>
        )}
      </div>
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("reports.col_class")}</TableHead>
              <TableHead>{t("reports.col_jahrgang")}</TableHead>
              <TableHead className="text-right">{t("reports.col_students")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={3} />)
            ) : q.isError ? (
              <ErrorRow columns={3} />
            ) : (
              (q.data?.rows ?? []).map((row) => (
                <TableRow key={row.class_id}>
                  <TableCell className="font-medium">
                    {row.name}
                    {row.kuerzel ? (
                      <span className="ml-2 text-xs text-muted-foreground">({row.kuerzel})</span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    {gradeRangeLabel(row.jahrgangsstufe, row.jahrgangsstufe_bis)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.student_count}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function TeacherWorkloadSection(): JSX.Element {
  const { t } = useTranslation();
  const q = useTeacherWorkload();
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{t("reports.workload_title")}</h2>
      <p className="text-sm text-muted-foreground">{t("reports.workload_intro")}</p>
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("reports.col_teacher")}</TableHead>
              <TableHead className="text-right">{t("classes.role_haupt")}</TableHead>
              <TableHead className="text-right">{t("classes.role_co")}</TableHead>
              <TableHead className="text-right">{t("classes.role_stellvertretung")}</TableHead>
              <TableHead className="text-right">{t("reports.col_total")}</TableHead>
              <TableHead>{t("reports.col_classes")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={6} />)
            ) : q.isError ? (
              <ErrorRow columns={6} />
            ) : (
              (q.data?.rows ?? []).map((row) => (
                <TableRow key={row.ad_object_guid}>
                  <TableCell>
                    <div className="flex flex-col leading-tight">
                      <span className="font-medium">{row.display_name ?? row.upn ?? "—"}</span>
                      {row.upn && <span className="text-xs text-muted-foreground">{row.upn}</span>}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.haupt_count}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.co_count}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.stellvertretung_count}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{row.total}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {row.classes.length > 0 ? row.classes.join(", ") : "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

const DAY_OPTIONS = [7, 30, 90, 365] as const;

function ActivitySection(): JSX.Element {
  const { t } = useTranslation();
  const [days, setDays] = useState<number>(30);
  const q = useActivityReport(days);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">{t("reports.activity_title")}</h2>
        <div role="tablist" className="inline-flex rounded-md border bg-card p-0.5">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              role="tab"
              aria-selected={days === d}
              onClick={() => setDays(d)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t("reports.last_n_days", { count: d })}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("reports.col_action")}</TableHead>
              <TableHead className="text-right">{t("reports.col_count")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={2} />)
            ) : q.isError ? (
              <ErrorRow columns={2} />
            ) : (
              (q.data?.rows ?? []).map((row) => (
                <TableRow key={row.action}>
                  <TableCell>
                    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{row.action}</code>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.count}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
