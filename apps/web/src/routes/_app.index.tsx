import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import {
  useClasses,
  useCurrentUser,
  useDepartments,
  useEnabledModules,
  useInstanceProfile,
  useSchools,
  useUsers,
} from "@/api/hooks";
import type { AdUserOut, ClassOut, DepartmentOut } from "@/api/types";
import { SkeletonRow } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { gradeRangeLabel } from "@/lib/grade";
import { useTerms } from "@/lib/useTerms";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/")({
  component: DashboardPage,
});

function DashboardPage(): JSX.Element {
  const me = useCurrentUser();
  const profile = useInstanceProfile().data ?? "school";
  const modules = useEnabledModules();
  const hasClasses = modules.data?.has("classes") ?? true;
  const hasDepartments = modules.data?.has("departments") ?? false;
  const isManager =
    me.data?.is_admin || (me.data?.roles ?? []).some((r) => r === "schulleitung" || r === "smi");

  // The edition decides the overview, driven by the INSTANCE PROFILE (not the
  // module set): the company edition never renders the school dashboard — which
  // would query the disabled /classes endpoint and surface a spurious error —
  // it always gets the company overview (Standorte/Abteilungen/Mitarbeitende).
  if (profile === "company") {
    return isManager ? (
      <CompanyDashboard />
    ) : (
      <SimpleDashboard hasClasses={false} hasDepartments={hasDepartments} />
    );
  }
  if (!isManager) {
    return <SimpleDashboard hasClasses={hasClasses} hasDepartments={hasDepartments} />;
  }
  return <SchulleitungDashboard />;
}

// ---------------------------------------------------------------------------
// Schulleitung / Admin / SMI view
// ---------------------------------------------------------------------------

function SchulleitungDashboard(): JSX.Element {
  const { t } = useTranslation();
  const { tt } = useTerms();
  const classes = useClasses();
  const allStudents = useUsers({ kind: "student", limit: 1 });
  const allTeachers = useUsers({ kind: "teacher", limit: 1 });
  const disabledUsers = useUsers({ enabled: false, limit: 50 });

  const activeClasses = classes.data?.filter((c) => c.status === "active") ?? [];
  const archivedClasses = classes.data?.filter((c) => c.status === "archived") ?? [];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
        <p className="text-sm text-muted-foreground">{tt("dashboard.intro")}</p>
      </header>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("dashboard.stat_active_classes")}
          value={classes.isLoading ? null : activeClasses.length}
          sub={
            archivedClasses.length > 0
              ? t("dashboard.stat_archived_classes", { count: archivedClasses.length })
              : undefined
          }
          href="/classes"
        />
        <StatCard
          label={t("dashboard.stat_teachers")}
          value={allTeachers.isLoading ? null : (allTeachers.data?.total ?? null)}
          href="/users?kind=teacher"
        />
        <StatCard
          label={t("dashboard.stat_students")}
          value={allStudents.isLoading ? null : (allStudents.data?.total ?? null)}
          href="/users?kind=student"
        />
        <StatCard
          label={t("dashboard.stat_disabled")}
          value={disabledUsers.isLoading ? null : (disabledUsers.data?.total ?? null)}
          tone={!disabledUsers.isLoading && (disabledUsers.data?.total ?? 0) > 0 ? "warn" : "ok"}
          href="/users"
        />
      </div>

      {/* All active classes */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">{t("dashboard.classes_section")}</h2>
          <Link to="/classes" className="text-sm text-primary hover:underline">
            {t("dashboard.classes_all")}
          </Link>
        </div>

        {classes.isError ? (
          <ErrorBanner message={t("errors.generic")} />
        ) : (
          <div className="overflow-hidden rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("classes.name")}</TableHead>
                  <TableHead>{t("classes.kuerzel")}</TableHead>
                  <TableHead>{t("classes.jahrgangsstufe")}</TableHead>
                  <TableHead>{t("classes.status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {classes.isLoading
                  ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} columns={4} />)
                  : activeClasses.map((c) => <ClassRow key={c.id} cls={c} />)}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      {/* Disabled accounts — Off-Boarding queue */}
      {(disabledUsers.data?.total ?? 0) > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t("dashboard.disabled_section")}</h2>
          <p className="text-sm text-muted-foreground">{t("dashboard.disabled_intro")}</p>
          <div className="overflow-hidden rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("users.name")}</TableHead>
                  <TableHead>{t("users.kind")}</TableHead>
                  <TableHead className="text-right">{t("users.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {disabledUsers.isLoading
                  ? Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} columns={3} />)
                  : disabledUsers.data?.items.map((u) => (
                      <DisabledUserRow key={u.ad_object_guid} user={u} />
                    ))}
              </TableBody>
            </Table>
          </div>
          {(disabledUsers.data?.total ?? 0) > 50 && (
            <p className="text-xs text-muted-foreground">
              {t("dashboard.disabled_more", { count: disabledUsers.data!.total })}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Company edition view (Standorte / Abteilungen / Mitarbeitende)
// ---------------------------------------------------------------------------

function CompanyDashboard(): JSX.Element {
  const { t } = useTranslation();
  const { tt } = useTerms();
  const units = useSchools();
  const departments = useDepartments();
  const allMembers = useUsers({ limit: 1 });
  const disabledUsers = useUsers({ enabled: false, limit: 50 });

  const activeDepartments = departments.data?.filter((d) => d.status === "active") ?? [];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
        <p className="text-sm text-muted-foreground">{tt("dashboard.intro")}</p>
      </header>

      {/* Summary cards — company vocabulary, no Klassen anywhere. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={tt("dashboard.stat_units")}
          value={units.isLoading ? null : (units.data?.length ?? null)}
          href="/admin/schools"
        />
        <StatCard
          label={t("dashboard.stat_departments")}
          value={departments.isLoading ? null : activeDepartments.length}
          href="/departments"
        />
        <StatCard
          label={tt("dashboard.stat_members")}
          value={allMembers.isLoading ? null : (allMembers.data?.total ?? null)}
          href="/users"
        />
        <StatCard
          label={t("dashboard.stat_disabled")}
          value={disabledUsers.isLoading ? null : (disabledUsers.data?.total ?? null)}
          tone={!disabledUsers.isLoading && (disabledUsers.data?.total ?? 0) > 0 ? "warn" : "ok"}
          href="/users"
        />
      </div>

      {/* Active departments */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">{t("dashboard.departments_section")}</h2>
          <Link to="/departments" className="text-sm text-primary hover:underline">
            {t("dashboard.departments_all")}
          </Link>
        </div>

        {departments.isLoading ? (
          <div className="overflow-hidden rounded-md border bg-card">
            <Table>
              <TableBody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <SkeletonRow key={i} columns={2} />
                ))}
              </TableBody>
            </Table>
          </div>
        ) : departments.isError || activeDepartments.length === 0 ? (
          <p className="rounded-md border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
            {t("dashboard.departments_empty")}
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("departments.name")}</TableHead>
                  <TableHead>{t("departments.kuerzel")}</TableHead>
                  <TableHead className="text-right">{t("departments.members")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeDepartments.map((d) => (
                  <DepartmentRow key={d.id} dept={d} />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      {/* Disabled accounts — Off-Boarding queue (edition-neutral) */}
      {(disabledUsers.data?.total ?? 0) > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t("dashboard.disabled_section")}</h2>
          <p className="text-sm text-muted-foreground">{t("dashboard.disabled_intro")}</p>
          <div className="overflow-hidden rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("users.name")}</TableHead>
                  <TableHead>{t("users.kind")}</TableHead>
                  <TableHead className="text-right">{t("users.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {disabledUsers.isLoading
                  ? Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} columns={3} />)
                  : disabledUsers.data?.items.map((u) => (
                      <DisabledUserRow key={u.ad_object_guid} user={u} />
                    ))}
              </TableBody>
            </Table>
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Non-manager fallback: simple nav cards, gated to the enabled modules
// ---------------------------------------------------------------------------

function SimpleDashboard({
  hasClasses,
  hasDepartments,
}: {
  hasClasses: boolean;
  hasDepartments: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  const { tt } = useTerms();
  const me = useCurrentUser();
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("app.title")}</h1>
        <p className="text-sm text-muted-foreground">{tt("app.tagline")}</p>
      </header>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("auth.logged_in_as")}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {me.data?.upn ?? t("common.loading")}
          {" · "}
          {me.data?.roles.length ? me.data.roles.join(", ") : t("auth.no_roles")}
        </CardContent>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {hasClasses ? (
          <Link to="/classes" className="block">
            <Card className="transition hover:bg-accent hover:text-accent-foreground">
              <CardHeader>
                <CardTitle className="text-base">{t("nav.classes")}</CardTitle>
              </CardHeader>
            </Card>
          </Link>
        ) : null}
        {hasDepartments ? (
          <Link to="/departments" className="block">
            <Card className="transition hover:bg-accent hover:text-accent-foreground">
              <CardHeader>
                <CardTitle className="text-base">{t("nav.departments")}</CardTitle>
              </CardHeader>
            </Card>
          </Link>
        ) : null}
        <Link to="/users" className="block">
          <Card className="transition hover:bg-accent hover:text-accent-foreground">
            <CardHeader>
              <CardTitle className="text-base">{t("nav.users")}</CardTitle>
            </CardHeader>
          </Card>
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  href,
  tone = "ok",
}: {
  label: string;
  value: number | null;
  sub?: string;
  href?: string;
  tone?: "ok" | "warn";
}): JSX.Element {
  const inner = (
    <Card className={href ? "transition hover:bg-accent hover:text-accent-foreground" : ""}>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p
          className={`text-3xl font-bold ${tone === "warn" ? "text-destructive" : "text-foreground"}`}
        >
          {value === null ? "—" : value}
        </p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
  return href ? (
    <Link to={href as never} className="block">
      {inner}
    </Link>
  ) : (
    inner
  );
}

function ClassRow({ cls }: { cls: ClassOut }): JSX.Element {
  const { t } = useTranslation();
  return (
    <TableRow>
      <TableCell>
        <Link
          to="/classes/$classId"
          params={{ classId: String(cls.id) }}
          className="font-medium hover:underline"
        >
          {cls.name}
        </Link>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{cls.kuerzel ?? "—"}</TableCell>
      <TableCell className="text-sm">
        {gradeRangeLabel(cls.jahrgangsstufe, cls.jahrgangsstufe_bis)}
      </TableCell>
      <TableCell>
        {cls.status === "active" ? (
          <StatusPill tone="ok">{t("classes.status_active")}</StatusPill>
        ) : (
          <StatusPill tone="muted">{t("classes.status_archived")}</StatusPill>
        )}
      </TableCell>
    </TableRow>
  );
}

function DepartmentRow({ dept }: { dept: DepartmentOut }): JSX.Element {
  return (
    <TableRow>
      <TableCell>
        <Link
          to="/departments/$departmentId"
          params={{ departmentId: String(dept.id) }}
          className="font-medium hover:underline"
        >
          {dept.name}
        </Link>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{dept.kuerzel ?? "—"}</TableCell>
      <TableCell className="text-right text-sm tabular-nums">{dept.member_count}</TableCell>
    </TableRow>
  );
}

function DisabledUserRow({ user: u }: { user: AdUserOut }): JSX.Element {
  const { t } = useTranslation();
  return (
    <TableRow>
      <TableCell>
        <Link
          to="/users/$guid"
          params={{ guid: u.ad_object_guid }}
          className="flex flex-col leading-tight hover:underline"
        >
          <span className="font-medium">{displayLabel(u)}</span>
          <span className="text-xs text-muted-foreground">{u.upn}</span>
        </Link>
      </TableCell>
      <TableCell>
        <StatusPill tone="muted">
          {u.kind === "teacher" ? t("users.kind_teacher") : t("users.kind_student")}
        </StatusPill>
      </TableCell>
      <TableCell className="text-right">
        <Link
          to="/users/$guid"
          params={{ guid: u.ad_object_guid }}
          className="inline-flex h-8 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          {t("dashboard.disabled_manage")}
        </Link>
      </TableCell>
    </TableRow>
  );
}

function ErrorBanner({ message }: { message: string }): JSX.Element {
  return (
    <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {message}
    </p>
  );
}
