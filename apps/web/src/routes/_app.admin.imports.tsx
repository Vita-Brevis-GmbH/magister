import { createFileRoute } from "@tanstack/react-router";
import { useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  downloadHandouts,
  useApplyImport,
  useCancelImport,
  useCurrentUser,
  useImportJob,
  useImportJobs,
  useSchools,
  useStageImport,
} from "@/api/hooks";
import type { ImportJobDetailOut, ImportKind, ProvisionedCredential } from "@/api/types";
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
import { useFormatters } from "@/lib/useFormatters";

export const Route = createFileRoute("/_app/admin/imports")({
  component: ImportsPage,
});

const ALL_KINDS: ImportKind[] = ["classes", "class_memberships", "class_teachers", "students"];

function ImportsPage(): JSX.Element {
  const { t } = useTranslation();
  const fmt = useFormatters();
  const jobs = useImportJobs();
  const [openJobId, setOpenJobId] = useState<number | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">{t("imports.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("imports.intro")}</p>
        </div>
        <Button onClick={() => setWizardOpen(true)}>{t("imports.new_button")}</Button>
      </header>

      {jobs.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : !jobs.isLoading && (jobs.data ?? []).length === 0 ? (
        <EmptyState message={t("imports.empty")} />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("imports.col_created")}</TableHead>
                <TableHead>{t("imports.col_kind")}</TableHead>
                <TableHead>{t("imports.col_file")}</TableHead>
                <TableHead>{t("imports.col_status")}</TableHead>
                <TableHead className="text-right">{t("imports.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.isLoading
                ? Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={5} />)
                : (jobs.data ?? []).map((j) => (
                    <TableRow key={j.id}>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {fmt.formatDateTime(j.created_at)}
                      </TableCell>
                      <TableCell>
                        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{j.kind}</code>
                      </TableCell>
                      <TableCell className="text-sm">
                        {j.filename ?? <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell>
                        <JobStatusPill status={j.status} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" onClick={() => setOpenJobId(j.id)}>
                          {t("imports.view_button")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      {wizardOpen && (
        <NewImportWizard
          onClose={() => setWizardOpen(false)}
          onStaged={(jobId) => {
            setWizardOpen(false);
            setOpenJobId(jobId);
          }}
        />
      )}
      {openJobId !== null && (
        <JobDetailModal jobId={openJobId} onClose={() => setOpenJobId(null)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

function NewImportWizard({
  onClose,
  onStaged,
}: {
  onClose: () => void;
  onStaged: (jobId: number) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [kind, setKind] = useState<ImportKind>("classes");
  const [file, setFile] = useState<File | null>(null);
  const [schoolId, setSchoolId] = useState("");
  const stage = useStageImport();
  const me = useCurrentUser();
  const schools = useSchools();

  // Admins are not bound to a single school and must pick the target; a
  // school-scoped user with exactly one school has it derived server-side.
  const scope = me.data?.school_scope ?? [];
  const mustPickSchool = (me.data?.is_admin ?? false) || scope.length > 1;

  function handleFile(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    stage.reset();
  }

  function handleSubmit() {
    if (!file) return;
    if (mustPickSchool && !schoolId) return;
    stage.mutate(
      { kind, file, schoolId: schoolId ? Number(schoolId) : undefined },
      {
        onSuccess: (data) => onStaged(data.id),
      },
    );
  }

  return (
    <ModalShell title={t("imports.new_title")} onClose={onClose} wide>
      <div className="space-y-5">
        <div className="space-y-2">
          <label className="text-sm font-medium">{t("imports.kind_label")}</label>
          <div
            role="tablist"
            className="inline-flex flex-wrap rounded-md border bg-background p-0.5"
          >
            {ALL_KINDS.map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                onClick={() => {
                  setKind(k);
                  setFile(null);
                  stage.reset();
                }}
                className={
                  kind === k
                    ? "rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
                    : "rounded px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {t(`imports.kind_${k}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
          <p className="text-muted-foreground">{t(`imports.kind_${kind}_desc`)}</p>
          <p className="mt-2">
            <a
              href={`/api/imports/templates/${kind}.csv`}
              className="text-primary hover:underline"
              download={`${kind}.csv`}
            >
              ⬇ {t("imports.download_template")}
            </a>
          </p>
        </div>

        {mustPickSchool && (
          <div className="space-y-1">
            <label htmlFor="import-school" className="text-sm font-medium">
              {t("imports.school_label")}
            </label>
            <select
              id="import-school"
              value={schoolId}
              onChange={(e) => setSchoolId(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">{t("imports.school_placeholder")}</option>
              {(schools.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.kuerzel})
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{t("imports.school_hint")}</p>
          </div>
        )}

        <div className="space-y-1">
          <label htmlFor="import-file" className="text-sm font-medium">
            {t("imports.file_label")}
          </label>
          <input
            id="import-file"
            type="file"
            accept=".csv,text/csv"
            onChange={handleFile}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
          />
        </div>

        {stage.isError && (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {stageErrorMessage(stage.error, t)}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={!file || (mustPickSchool && !schoolId) || stage.isPending}
            onClick={handleSubmit}
          >
            {stage.isPending ? t("common.loading") : t("imports.upload_button")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Job detail
// ---------------------------------------------------------------------------

function JobDetailModal({ jobId, onClose }: { jobId: number; onClose: () => void }): JSX.Element {
  const { t, i18n } = useTranslation();
  const fmt = useFormatters();
  const q = useImportJob(jobId);
  const apply = useApplyImport();
  const cancel = useCancelImport();
  const [credentials, setCredentials] = useState<ProvisionedCredential[]>([]);
  const [handoutError, setHandoutError] = useState(false);

  function handleApply() {
    apply.mutate(jobId, {
      onSuccess: (data) => setCredentials(data.credentials ?? []),
    });
  }

  const uiLang = (["de", "fr", "it"] as const).find((l) => i18n.language.startsWith(l)) ?? "de";
  const [handoutLang, setHandoutLang] = useState<"de" | "fr" | "it">(uiLang);

  async function handleDownloadHandouts() {
    setHandoutError(false);
    try {
      await downloadHandouts(credentials, "", handoutLang);
    } catch {
      setHandoutError(true);
    }
  }
  function handleCancel() {
    cancel.mutate(jobId, { onSuccess: () => onClose() });
  }

  const job = q.data;

  return (
    <ModalShell
      title={
        job ? `${t("imports.detail_title")} · #${job.id} · ${job.kind}` : t("imports.detail_title")
      }
      onClose={onClose}
      wide
    >
      {q.isLoading || !job ? (
        <p>{t("common.loading")}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <JobStatusPill status={job.status} />
            <span className="text-xs text-muted-foreground">
              {t("imports.created_by")}: {job.created_by_upn ?? "—"}
            </span>
            <span className="text-xs text-muted-foreground">
              {fmt.formatDateTime(job.created_at)}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <CountTile label={t("imports.action_create")} value={job.counts.create} tone="ok" />
            <CountTile label={t("imports.action_update")} value={job.counts.update} tone="warn" />
            <CountTile label={t("imports.action_skip")} value={job.counts.skip} tone="muted" />
            <CountTile label={t("imports.action_error")} value={job.counts.error} tone="danger" />
          </div>

          {apply.isError && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {t("errors.generic")}
            </div>
          )}

          {credentials.length > 0 && (
            <div className="space-y-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-3">
              <p className="text-sm font-medium">
                {t("imports.credentials_ready", { count: credentials.length })}
              </p>
              <p className="text-xs text-muted-foreground">{t("imports.credentials_hint")}</p>
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted-foreground" htmlFor="handout-lang">
                  {t("imports.handout_language")}
                </label>
                <select
                  id="handout-lang"
                  value={handoutLang}
                  onChange={(e) => setHandoutLang(e.target.value as "de" | "fr" | "it")}
                  className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                >
                  <option value="de">Deutsch</option>
                  <option value="fr">Français</option>
                  <option value="it">Italiano</option>
                </select>
                <Button size="sm" onClick={handleDownloadHandouts}>
                  {t("imports.download_handouts")}
                </Button>
              </div>
              {handoutError && <p className="text-xs text-destructive">{t("errors.generic")}</p>}
            </div>
          )}

          <div className="max-h-[55vh] overflow-auto rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead>{t("imports.col_row_action")}</TableHead>
                  <TableHead>{t("imports.col_row_data")}</TableHead>
                  <TableHead>{t("imports.col_row_errors")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {job.rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-xs text-muted-foreground">{r.row_num}</TableCell>
                    <TableCell>
                      <ActionPill action={r.action} />
                      {r.applied_error && (
                        <p className="mt-1 text-xs text-destructive">{r.applied_error}</p>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      <code className="text-muted-foreground">{summarizeRow(r.raw_data)}</code>
                    </TableCell>
                    <TableCell className="text-xs text-destructive">
                      {r.errors.length > 0 ? r.errors.join("; ") : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              {t("common.close")}
            </Button>
            {job.status === "staged" && (
              <>
                <Button variant="outline" disabled={cancel.isPending} onClick={handleCancel}>
                  {t("imports.cancel_button")}
                </Button>
                <Button
                  disabled={apply.isPending || job.counts.create + job.counts.update === 0}
                  onClick={handleApply}
                >
                  {apply.isPending
                    ? t("common.loading")
                    : t("imports.apply_button", {
                        count: job.counts.create + job.counts.update,
                      })}
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function summarizeRow(raw: Record<string, string>): string {
  return Object.entries(raw)
    .map(([k, v]) => `${k}=${v || "∅"}`)
    .join(" · ");
}

function stageErrorMessage(err: ApiError, t: (k: string) => string): string {
  if (err.status === 400) {
    if (err.code?.includes("csv header")) return t("imports.error_invalid_header");
    if (err.code === "csv_not_utf8") return t("imports.error_not_utf8");
    if (err.code === "unknown_kind") return t("imports.error_unknown_kind");
    if (err.code === "school_id_required_for_admin") return t("imports.error_school_required");
    return err.code || t("errors.generic");
  }
  return t("errors.generic");
}

function ModalShell({
  title,
  onClose,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={
          wide
            ? "w-full max-w-3xl rounded-lg border bg-card p-6 shadow-lg"
            : "w-full max-w-md rounded-lg border bg-card p-6 shadow-lg"
        }
      >
        <h2 className="mb-4 font-serif text-xl font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}

function JobStatusPill({ status }: { status: ImportJobDetailOut["status"] }): JSX.Element {
  const { t } = useTranslation();
  if (status === "applied") return <StatusPill tone="ok">{t("imports.status_applied")}</StatusPill>;
  if (status === "cancelled")
    return <StatusPill tone="muted">{t("imports.status_cancelled")}</StatusPill>;
  return <StatusPill tone="warn">{t("imports.status_staged")}</StatusPill>;
}

function ActionPill({ action }: { action: "create" | "update" | "skip" | "error" }): JSX.Element {
  const { t } = useTranslation();
  if (action === "create") return <StatusPill tone="ok">{t("imports.action_create")}</StatusPill>;
  if (action === "update") return <StatusPill tone="warn">{t("imports.action_update")}</StatusPill>;
  if (action === "skip") return <StatusPill tone="muted">{t("imports.action_skip")}</StatusPill>;
  return <StatusPill tone="danger">{t("imports.action_error")}</StatusPill>;
}

function CountTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "warn" | "muted" | "danger";
}): JSX.Element {
  const colour =
    tone === "ok"
      ? "text-emerald-700"
      : tone === "warn"
        ? "text-amber-700"
        : tone === "danger"
          ? "text-destructive"
          : "text-muted-foreground";
  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-semibold ${colour}`}>{value}</p>
    </div>
  );
}

function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
