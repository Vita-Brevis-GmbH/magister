import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useArchiveClass,
  useClassMemberships,
  useClasses,
  useCreateClass,
  useCurrentUser,
  usePromoteClass,
  useSchools,
  useUpdateClass,
} from "@/api/hooks";
import type { ClassOut, ClassPromotionResult } from "@/api/types";
import { Pagination } from "@/components/Pagination";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { gradeRangeLabel } from "@/lib/grade";
import { usePagedList } from "@/lib/usePagedList";

export const Route = createFileRoute("/_app/classes")({
  component: ClassesPage,
});

function ClassesPage(): JSX.Element {
  // When a child route (e.g. /classes/$classId) is active, hand off to
  // its Outlet — TanStack file-based routing treats _app.classes.tsx as
  // the parent layout, so without this the list would stack on top of
  // the detail page.
  const childMatches = useChildMatches();
  const { t } = useTranslation();
  const q = useClasses();
  const me = useCurrentUser();
  const schools = useSchools();
  const schoolName = (id: number): string =>
    schools.data?.find((s) => s.id === id)?.name ?? String(id);
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ClassOut | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<ClassOut | null>(null);
  const [promoteSource, setPromoteSource] = useState<ClassOut | null>(null);
  const paged = usePagedList(q.data ?? []);

  if (childMatches.length > 0) return <Outlet />;

  // Schulleitung + admin can write; KL is read-only here (their write surface
  // is the class-detail page's students section).
  const canWrite = me.data?.is_admin || (me.data?.roles ?? []).includes("schulleitung");

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="font-serif text-2xl font-semibold">{t("classes.title")}</h1>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            {t("classes.create_button")}
          </Button>
        ) : null}
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : (q.data ?? []).length === 0 ? (
        <p className="text-muted-foreground">{t("classes.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("classes.name")}</TableHead>
              <TableHead>{t("classes.kuerzel")}</TableHead>
              <TableHead>{t("classes.jahrgangsstufe")}</TableHead>
              <TableHead>{t("classes.school")}</TableHead>
              <TableHead>{t("classes.status")}</TableHead>
              {canWrite ? (
                <TableHead className="w-0 text-right">{t("users.actions")}</TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {paged.pageItems.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="p-0 font-medium">
                  {/* Link fills the whole cell so the click target is the full
                      name column, not just the text glyphs. */}
                  <Link
                    to="/classes/$classId"
                    params={{ classId: String(c.id) }}
                    className="block px-4 py-3 text-primary underline-offset-2 hover:underline"
                  >
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>{c.kuerzel ?? "–"}</TableCell>
                <TableCell>{gradeRangeLabel(c.jahrgangsstufe, c.jahrgangsstufe_bis)}</TableCell>
                <TableCell>{schoolName(c.school_id)}</TableCell>
                <TableCell>
                  {c.status === "active"
                    ? t("classes.status_active")
                    : t("classes.status_archived")}
                </TableCell>
                {canWrite ? (
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      {c.status === "active" ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setPromoteSource(c)}
                        >
                          {t("classes.promote_button")}
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setEditTarget(c)}
                      >
                        {t("classes.edit_button")}
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        onClick={() => setArchiveTarget(c)}
                      >
                        {t("classes.archive_button")}
                      </Button>
                    </div>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!q.isLoading && !q.isError ? <Pagination paged={paged} /> : null}

      <CreateClassModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        defaultSchoolId={me.data?.school_scope[0] ?? null}
        isAdmin={me.data?.is_admin ?? false}
      />
      <EditClassModal target={editTarget} onClose={() => setEditTarget(null)} />
      <ArchiveClassDialog target={archiveTarget} onClose={() => setArchiveTarget(null)} />
      <PromoteClassWizard
        source={promoteSource}
        allClasses={q.data ?? []}
        onClose={() => setPromoteSource(null)}
      />
    </div>
  );
}

interface CreateProps {
  open: boolean;
  onClose: () => void;
  defaultSchoolId: number | null;
  isAdmin: boolean;
}

export function CreateClassModal({
  open,
  onClose,
  defaultSchoolId,
  isAdmin,
}: CreateProps): JSX.Element {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [kuerzel, setKuerzel] = useState("");
  const [jahrgangsstufe, setJahrgangsstufe] = useState("");
  const [jahrgangsstufeBis, setJahrgangsstufeBis] = useState("");
  const [details, setDetails] = useState("");
  const [schoolId, setSchoolId] = useState(defaultSchoolId !== null ? String(defaultSchoolId) : "");
  const schools = useSchools();
  const create = useCreateClass();

  function reset(): void {
    setName("");
    setKuerzel("");
    setJahrgangsstufe("");
    setJahrgangsstufeBis("");
    setDetails("");
    setSchoolId(defaultSchoolId !== null ? String(defaultSchoolId) : "");
    create.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    create.mutate(
      {
        name,
        kuerzel: kuerzel || null,
        jahrgangsstufe: Number(jahrgangsstufe),
        jahrgangsstufe_bis: jahrgangsstufeBis === "" ? null : Number(jahrgangsstufeBis),
        details: details || null,
        ...(isAdmin && { school_id: Number(schoolId) }),
      },
      {
        onSuccess: () => {
          reset();
          onClose();
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("classes.create_title")}</DialogTitle>
          <DialogDescription>{t("classes.create_description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {create.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {classErrorKey(create.error, t)}
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="class-name">{t("classes.name")}</Label>
            <Input
              id="class-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={64}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="class-kuerzel">{t("classes.kuerzel")}</Label>
            <Input
              id="class-kuerzel"
              value={kuerzel}
              onChange={(e) => setKuerzel(e.target.value)}
              maxLength={32}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="class-jahrgang">{t("classes.jahrgangsstufe_von")}</Label>
              <Input
                id="class-jahrgang"
                type="number"
                min={-1}
                max={13}
                value={jahrgangsstufe}
                onChange={(e) => setJahrgangsstufe(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="class-jahrgang-bis">{t("classes.jahrgangsstufe_bis")}</Label>
              <Input
                id="class-jahrgang-bis"
                type="number"
                min={-1}
                max={13}
                value={jahrgangsstufeBis}
                onChange={(e) => setJahrgangsstufeBis(e.target.value)}
                placeholder={t("classes.jahrgangsstufe_bis_placeholder")}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("classes.jahrgangsstufe_hint")}</p>
          <div className="space-y-1">
            <Label htmlFor="class-details">{t("classes.details")}</Label>
            <textarea
              id="class-details"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              maxLength={2000}
              rows={2}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          {isAdmin ? (
            <div className="space-y-1">
              <Label htmlFor="class-school-id">{t("classes.school")}</Label>
              <select
                id="class-school-id"
                value={schoolId}
                onChange={(e) => setSchoolId(e.target.value)}
                required
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">{t("classes.school_select_placeholder")}</option>
                {(schools.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.kuerzel})
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{t("classes.school_id_admin_hint")}</p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                onClose();
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t("common.loading") : t("classes.create_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface RenameProps {
  target: ClassOut | null;
  onClose: () => void;
}

export function EditClassModal({ target, onClose }: RenameProps): JSX.Element {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [kuerzel, setKuerzel] = useState("");
  const [details, setDetails] = useState("");
  const [jahrgangsstufe, setJahrgangsstufe] = useState("");
  const [jahrgangsstufeBis, setJahrgangsstufeBis] = useState("");
  const [hydratedId, setHydratedId] = useState<number | null>(null);
  const update = useUpdateClass(target?.id ?? 0);

  // Hydrate from the target whenever a new class opens. Controlled inputs keep
  // the grade fields honest — a stale "" would otherwise submit as grade 0 (KG2).
  if (target && hydratedId !== target.id) {
    setName(target.name);
    setKuerzel(target.kuerzel ?? "");
    setDetails(target.details ?? "");
    setJahrgangsstufe(String(target.jahrgangsstufe));
    setJahrgangsstufeBis(
      target.jahrgangsstufe_bis != null ? String(target.jahrgangsstufe_bis) : "",
    );
    setHydratedId(target.id);
    update.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!target) return;
    const bisNum = jahrgangsstufeBis === "" ? null : Number(jahrgangsstufeBis);
    const vonNum = Number(jahrgangsstufe);
    update.mutate(
      {
        ...(name !== target.name && { name }),
        ...(kuerzel !== (target.kuerzel ?? "") && { kuerzel: kuerzel || null }),
        ...(details !== (target.details ?? "") && { details }),
        ...(jahrgangsstufe !== "" &&
          vonNum !== target.jahrgangsstufe && { jahrgangsstufe: vonNum }),
        ...(bisNum !== (target.jahrgangsstufe_bis ?? null) && { jahrgangsstufe_bis: bisNum }),
      },
      {
        onSuccess: () => {
          setHydratedId(null);
          onClose();
        },
      },
    );
  }

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("classes.edit_title")}</DialogTitle>
          <DialogDescription>{target?.name}</DialogDescription>
        </DialogHeader>
        <form key={target?.id ?? "none"} onSubmit={handleSubmit} className="space-y-4">
          {update.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {classErrorKey(update.error, t)}
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="edit-name">{t("classes.name")}</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={64}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="edit-kuerzel">{t("classes.kuerzel")}</Label>
            <Input
              id="edit-kuerzel"
              value={kuerzel}
              onChange={(e) => setKuerzel(e.target.value)}
              maxLength={32}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="edit-jahrgang">{t("classes.jahrgangsstufe_von")}</Label>
              <Input
                id="edit-jahrgang"
                type="number"
                min={-1}
                max={13}
                value={jahrgangsstufe}
                onChange={(e) => setJahrgangsstufe(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="edit-jahrgang-bis">{t("classes.jahrgangsstufe_bis")}</Label>
              <Input
                id="edit-jahrgang-bis"
                type="number"
                min={-1}
                max={13}
                value={jahrgangsstufeBis}
                onChange={(e) => setJahrgangsstufeBis(e.target.value)}
                placeholder={t("classes.jahrgangsstufe_bis_placeholder")}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("classes.jahrgangsstufe_hint")}</p>
          <div className="space-y-1">
            <Label htmlFor="edit-details">{t("classes.details")}</Label>
            <textarea
              id="edit-details"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              maxLength={2000}
              rows={2}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? t("common.loading") : t("classes.edit_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface ArchiveProps {
  target: ClassOut | null;
  onClose: () => void;
}

export function ArchiveClassDialog({ target, onClose }: ArchiveProps): JSX.Element {
  const { t } = useTranslation();
  const archive = useArchiveClass();

  function handleConfirm(): void {
    if (!target) return;
    archive.mutate(target.id, {
      onSuccess: () => onClose(),
    });
  }

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("classes.archive_title")}</DialogTitle>
          <DialogDescription>
            {target ? t("classes.archive_confirm", { name: target.name }) : ""}
          </DialogDescription>
        </DialogHeader>
        {archive.isError ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {classErrorKey(archive.error, t)}
          </div>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleConfirm}
            disabled={archive.isPending}
          >
            {archive.isPending ? t("common.loading") : t("classes.archive_submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type PromoteStep = "pick" | "confirm" | "done";

function PromoteClassWizard({
  source,
  allClasses,
  onClose,
}: {
  source: ClassOut | null;
  allClasses: ClassOut[];
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [step, setStep] = useState<PromoteStep>("pick");
  const [targetId, setTargetId] = useState<number | "">("");
  const [archiveSource, setArchiveSource] = useState(false);
  const [result, setResult] = useState<ClassPromotionResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Advance each student's grade by +1 (default). Per-student exceptions go in
  // gradeOverrides (blank = +1 from the student's own grade; a number = exact).
  const [bumpGrade, setBumpGrade] = useState(true);
  const [gradeOverrides, setGradeOverrides] = useState<Record<string, string>>({});

  const promote = usePromoteClass(source?.id ?? 0);
  const memberships = useClassMemberships(source?.id ?? 0);
  const activeStudents = (memberships.data ?? []).filter((m) => m.valid_to === null);
  const allSelected = activeStudents.length > 0 && selected.size === activeStudents.length;

  const candidates = allClasses.filter((c) => c.id !== source?.id && c.status === "active");
  const target = candidates.find((c) => c.id === Number(targetId)) ?? null;

  function reset(): void {
    setStep("pick");
    setTargetId("");
    setArchiveSource(false);
    setResult(null);
    setSelected(new Set());
    setBumpGrade(true);
    setGradeOverrides({});
    promote.reset();
  }

  function toggle(guid: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(guid)) next.delete(guid);
      else next.add(guid);
      return next;
    });
  }

  function goToConfirm(): void {
    // Default to all active students selected; the user can deselect.
    setSelected(new Set(activeStudents.map((m) => m.ad_object_guid)));
    setStep("confirm");
  }

  function handleConfirm(): void {
    if (!source || !targetId) return;
    // Explicit per-student exceptions: only the ones the user typed a grade for.
    const overrides: Record<string, number> = {};
    if (bumpGrade) {
      for (const guid of selected) {
        const raw = (gradeOverrides[guid] ?? "").trim();
        if (raw !== "" && Number.isFinite(Number(raw))) overrides[guid] = Number(raw);
      }
    }
    promote.mutate(
      {
        target_class_id: Number(targetId),
        archive_source: archiveSource,
        bump_grade: bumpGrade,
        ...(Object.keys(overrides).length > 0 ? { grade_overrides: overrides } : {}),
        // Move all when every student is selected; otherwise the chosen subset.
        ...(allSelected ? {} : { student_guids: [...selected] }),
      },
      {
        onSuccess: (res) => {
          setResult(res);
          setStep("done");
        },
      },
    );
  }

  return (
    <Dialog
      open={source !== null}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-lg">
        {step === "pick" && (
          <>
            <DialogHeader>
              <DialogTitle>{t("classes.promote_title")}</DialogTitle>
              <DialogDescription>
                {t("classes.promote_source_label")}: <strong>{source?.name}</strong>
                {" · "}
                {t("classes.promote_active_students", { count: activeStudents.length })}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-1">
                <label htmlFor="promote-target" className="text-sm font-medium">
                  {t("classes.promote_target_label")}
                </label>
                <select
                  id="promote-target"
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : "")}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="">{t("classes.move_class_select_placeholder")}</option>
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                      {c.kuerzel ? ` (${c.kuerzel})` : ""}
                      {" · "}
                      {t("classes.jahrgangsstufe")}{" "}
                      {gradeRangeLabel(c.jahrgangsstufe, c.jahrgangsstufe_bis)}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={archiveSource}
                  onChange={(e) => setArchiveSource(e.target.checked)}
                  className="h-4 w-4 rounded border-input"
                />
                {t("classes.promote_archive_source")}
              </label>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  reset();
                  onClose();
                }}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                disabled={!targetId || activeStudents.length === 0}
                onClick={goToConfirm}
              >
                {t("classes.promote_preview_button")}
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "confirm" && target && (
          <>
            <DialogHeader>
              <DialogTitle>{t("classes.promote_confirm_title")}</DialogTitle>
              <DialogDescription>
                {t("classes.promote_confirm_desc", {
                  source: source?.name,
                  target: target.name,
                  count: selected.size,
                })}
              </DialogDescription>
            </DialogHeader>
            {promote.isError && (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t("errors.generic")}
              </div>
            )}
            <div className="max-h-48 overflow-y-auto rounded-md border bg-muted/30 p-2 text-sm">
              {activeStudents.length === 0 ? (
                <p className="text-muted-foreground">{t("classes.promote_no_students")}</p>
              ) : (
                <ul className="space-y-0.5">
                  {activeStudents.map((m) => (
                    <li key={m.id}>
                      <div className="flex items-center gap-2 text-xs">
                        <label className="flex flex-1 cursor-pointer items-center gap-2">
                          <input
                            type="checkbox"
                            checked={selected.has(m.ad_object_guid)}
                            onChange={() => toggle(m.ad_object_guid)}
                            className="h-3.5 w-3.5 rounded border-input"
                          />
                          <span className="truncate">{m.display_name ?? m.upn ?? "—"}</span>
                        </label>
                        {bumpGrade && selected.has(m.ad_object_guid) ? (
                          <input
                            type="number"
                            min={-1}
                            max={13}
                            value={gradeOverrides[m.ad_object_guid] ?? ""}
                            placeholder={t("classes.promote_grade_placeholder")}
                            onChange={(e) =>
                              setGradeOverrides((prev) => ({
                                ...prev,
                                [m.ad_object_guid]: e.target.value,
                              }))
                            }
                            className="h-6 w-16 rounded border border-input bg-background px-1 text-right"
                            title={t("classes.promote_grade_hint")}
                          />
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={bumpGrade}
                onChange={(e) => setBumpGrade(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              {t("classes.promote_bump_grade")}
            </label>
            {bumpGrade ? (
              <p className="text-xs text-muted-foreground">{t("classes.promote_grade_hint")}</p>
            ) : null}
            {archiveSource && (
              <p className="text-xs text-amber-600">
                {t("classes.promote_archive_warning", { name: source?.name })}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setStep("pick")}>
                {t("classes.promote_back")}
              </Button>
              <Button
                type="button"
                onClick={handleConfirm}
                disabled={promote.isPending || selected.size === 0}
              >
                {promote.isPending ? t("common.loading") : t("classes.promote_confirm_submit")}
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "done" && result && (
          <>
            <DialogHeader>
              <DialogTitle>{t("classes.promote_done_title")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-2 text-sm">
              <p>✓ {t("classes.promote_done_moved", { count: result.students_moved })}</p>
              {result.students_failed > 0 && (
                <p className="text-amber-600">
                  ⚠ {t("classes.promote_done_failed", { count: result.students_failed })}
                </p>
              )}
              {result.source_archived && (
                <p className="text-muted-foreground">
                  {t("classes.promote_done_archived", { name: source?.name })}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                onClick={() => {
                  reset();
                  onClose();
                }}
              >
                {t("common.close")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function classErrorKey(err: ApiError, t: (key: string) => string): string {
  if (err.status === 403) return t("errors.forbidden");
  if (err.status === 404 && err.code === "class_not_found") return t("classes.error_not_found");
  if (err.status === 400 && err.code === "school_id_required_for_admin")
    return t("classes.error_school_id_required");
  if (err.status === 400 && err.code === "cross_school_write") return t("errors.forbidden");
  return t("errors.generic");
}
