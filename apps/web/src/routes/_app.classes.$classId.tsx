import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, apiFetch } from "@/api/client";
import {
  useAddClassMembership,
  useAssignClassTeacher,
  useBulkAddClassMemberships,
  useClass,
  useClassMemberships,
  useClassTeachers,
  useClasses,
  useCurrentUser,
  useRemoveClassMembership,
  useRevokeClassTeacher,
  useUsers,
} from "@/api/hooks";
import type {
  AdUserOut,
  BulkClassMembershipResult,
  ClassMembershipOut,
  ClassTeacherOut,
  ClassTeacherRole,
} from "@/api/types";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/classes/$classId")({
  component: ClassDetailPage,
});

function ClassDetailPage(): JSX.Element {
  const { t } = useTranslation();
  const { classId: classIdStr } = Route.useParams();
  const classId = Number(classIdStr);

  const me = useCurrentUser();
  const klass = useClass(classId);
  const canManageTeachers = me.data?.is_admin || (me.data?.roles ?? []).includes("schulleitung");

  return (
    <div className="space-y-6">
      <div>
        <Link to="/classes" className="text-sm text-muted-foreground hover:underline">
          ← {t("classes.title")}
        </Link>
      </div>

      {klass.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : klass.isError ? (
        <p className="text-destructive">
          {klass.error instanceof ApiError && klass.error.status === 404
            ? t("classes.error_not_found")
            : t("errors.generic")}
        </p>
      ) : klass.data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="font-serif text-2xl">{klass.data.name}</CardTitle>
              <CardDescription>
                {t("classes.jahrgangsstufe")}: {klass.data.jahrgangsstufe}
                {klass.data.kuerzel ? ` · ${klass.data.kuerzel}` : ""}
                {" · "}
                {klass.data.status === "active"
                  ? t("classes.status_active")
                  : t("classes.status_archived")}
              </CardDescription>
            </CardHeader>
          </Card>

          <TeachersSection classId={classId} canManage={!!canManageTeachers} />
          <StudentsSection classId={classId} />
        </>
      ) : null}
    </div>
  );
}

// --- Teachers --------------------------------------------------------------

function TeachersSection({
  classId,
  canManage,
}: {
  classId: number;
  canManage: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  const q = useClassTeachers(classId);
  const revoke = useRevokeClassTeacher(classId);
  const [addOpen, setAddOpen] = useState(false);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{t("classes.teachers_title")}</CardTitle>
          <CardDescription>{t("classes.teachers_description")}</CardDescription>
        </div>
        {canManage ? (
          <Button type="button" size="sm" onClick={() => setAddOpen(true)}>
            {t("classes.assign_teacher_button")}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p>{t("common.loading")}</p>
        ) : q.isError ? (
          <p className="text-destructive">{t("errors.generic")}</p>
        ) : (q.data ?? []).length === 0 ? (
          <p className="text-muted-foreground">{t("classes.teachers_empty")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("classes.teacher_guid")}</TableHead>
                <TableHead>{t("classes.role")}</TableHead>
                <TableHead>{t("classes.valid_from")}</TableHead>
                <TableHead>{t("classes.valid_to")}</TableHead>
                {canManage ? (
                  <TableHead className="w-0 text-right">{t("users.actions")}</TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {(q.data ?? []).map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <PersonCell row={row} />
                  </TableCell>
                  <TableCell>{teacherRoleLabel(row.role, t)}</TableCell>
                  <TableCell>{formatIsoDate(row.valid_from)}</TableCell>
                  <TableCell>{row.valid_to ? formatIsoDate(row.valid_to) : "–"}</TableCell>
                  {canManage ? (
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => revoke.mutate(row.id)}
                        disabled={revoke.isPending || row.valid_to !== null}
                      >
                        {t("classes.revoke_teacher")}
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <AssignTeacherModal classId={classId} open={addOpen} onClose={() => setAddOpen(false)} />
    </Card>
  );
}

interface PersonRow {
  ad_object_guid: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

function PersonCell({ row }: { row: PersonRow }): JSX.Element {
  const upn = row.upn ?? "";
  const safe = { ...row, upn };
  return (
    <div className="flex items-center gap-3">
      <UserAvatar user={safe} size="sm" />
      <div className="flex flex-col leading-tight">
        <span className="font-medium">{displayLabel(safe)}</span>
        {upn ? <span className="text-xs text-muted-foreground">{upn}</span> : null}
      </div>
    </div>
  );
}

function AssignTeacherModal({
  classId,
  open,
  onClose,
}: {
  classId: number;
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<AdUserOut | null>(null);
  const [role, setRole] = useState<ClassTeacherRole>("haupt");
  const [validFrom, setValidFrom] = useState(today());
  const [validTo, setValidTo] = useState("");

  // Only fetch when there's a search term to avoid loading the whole teacher
  // pool just to open the modal.
  const users = useUsers(
    search.length >= 2 ? { kind: "teacher", search, limit: 10 } : { kind: "teacher", limit: 0 },
  );
  const assign = useAssignClassTeacher(classId);

  function reset(): void {
    setSearch("");
    setPicked(null);
    setRole("haupt");
    setValidFrom(today());
    setValidTo("");
    assign.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!picked) return;
    assign.mutate(
      {
        ad_object_guid: picked.ad_object_guid,
        role,
        valid_from: new Date(validFrom).toISOString(),
        valid_to: validTo ? new Date(validTo).toISOString() : null,
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
          <DialogTitle>{t("classes.assign_teacher_title")}</DialogTitle>
          <DialogDescription>{t("classes.assign_teacher_description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {assign.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t("errors.generic")}
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="teacher-search">{t("classes.search_teacher")}</Label>
            <Input
              id="teacher-search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPicked(null);
              }}
              placeholder={t("users.search_placeholder")}
            />
            {search.length >= 2 && users.data ? (
              <ul className="max-h-40 overflow-y-auto rounded-md border bg-background text-sm">
                {users.data.items.length === 0 ? (
                  <li className="px-3 py-2 text-muted-foreground">{t("users.empty")}</li>
                ) : (
                  users.data.items.map((u) => (
                    <li key={u.ad_object_guid}>
                      <button
                        type="button"
                        onClick={() => setPicked(u)}
                        className={`block w-full px-3 py-2 text-left hover:bg-accent ${
                          picked?.ad_object_guid === u.ad_object_guid ? "bg-accent" : ""
                        }`}
                      >
                        {u.upn}
                        {u.given_name || u.surname
                          ? ` — ${[u.given_name, u.surname].filter(Boolean).join(" ")}`
                          : ""}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
            {picked ? (
              <p className="text-xs text-muted-foreground">
                {t("classes.picked")}: <span className="font-mono">{picked.upn}</span>
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="teacher-role">{t("classes.role")}</Label>
            <select
              id="teacher-role"
              value={role}
              onChange={(e) => setRole(e.target.value as ClassTeacherRole)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="haupt">{t("classes.role_haupt")}</option>
              <option value="co">{t("classes.role_co")}</option>
              <option value="stellvertretung">{t("classes.role_stellvertretung")}</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="teacher-valid-from">{t("classes.valid_from")}</Label>
              <Input
                id="teacher-valid-from"
                type="date"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="teacher-valid-to">{t("classes.valid_to_optional")}</Label>
              <Input
                id="teacher-valid-to"
                type="date"
                value={validTo}
                onChange={(e) => setValidTo(e.target.value)}
              />
            </div>
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
            <Button type="submit" disabled={!picked || assign.isPending}>
              {assign.isPending ? t("common.loading") : t("classes.assign_teacher_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Students --------------------------------------------------------------

function StudentsSection({ classId }: { classId: number }): JSX.Element {
  const { t } = useTranslation();
  const me = useCurrentUser();
  const q = useClassMemberships(classId);
  const remove = useRemoveClassMembership(classId);
  const [addOpen, setAddOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);

  const canBulkManage =
    me.data?.is_admin || (me.data?.roles ?? []).some((r) => r === "schulleitung" || r === "smi");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{t("classes.students_title")}</CardTitle>
          <CardDescription>{t("classes.students_description")}</CardDescription>
        </div>
        <div className="flex gap-2">
          {canBulkManage ? (
            <>
              <Button type="button" size="sm" variant="outline" onClick={() => setMoveOpen(true)}>
                {t("classes.move_class_button")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setBulkOpen(true)}>
                {t("classes.bulk_add_button")}
              </Button>
            </>
          ) : null}
          <Button type="button" size="sm" onClick={() => setAddOpen(true)}>
            {t("classes.add_student_button")}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p>{t("common.loading")}</p>
        ) : q.isError ? (
          <p className="text-destructive">
            {q.error instanceof ApiError && q.error.status === 403
              ? t("errors.forbidden")
              : t("errors.generic")}
          </p>
        ) : (q.data ?? []).length === 0 ? (
          <p className="text-muted-foreground">{t("classes.students_empty")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("classes.student")}</TableHead>
                <TableHead>{t("classes.valid_from")}</TableHead>
                <TableHead>{t("classes.valid_to")}</TableHead>
                <TableHead className="w-0 text-right">{t("users.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(q.data ?? []).map((row: ClassMembershipOut) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <PersonCell row={row} />
                  </TableCell>
                  <TableCell>{formatIsoDate(row.valid_from)}</TableCell>
                  <TableCell>{row.valid_to ? formatIsoDate(row.valid_to) : "–"}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => remove.mutate(row.id)}
                      disabled={remove.isPending || row.valid_to !== null}
                    >
                      {t("classes.remove_student")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <AddStudentModal classId={classId} open={addOpen} onClose={() => setAddOpen(false)} />
      <BulkAddStudentsModal classId={classId} open={bulkOpen} onClose={() => setBulkOpen(false)} />
      <MoveClassModal
        classId={classId}
        students={q.data ?? []}
        open={moveOpen}
        onClose={() => setMoveOpen(false)}
      />
    </Card>
  );
}

function AddStudentModal({
  classId,
  open,
  onClose,
}: {
  classId: number;
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<AdUserOut | null>(null);
  const [validFrom, setValidFrom] = useState(today());

  const users = useUsers(
    search.length >= 2 ? { kind: "student", search, limit: 10 } : { kind: "student", limit: 0 },
  );
  const add = useAddClassMembership(classId);

  function reset(): void {
    setSearch("");
    setPicked(null);
    setValidFrom(today());
    add.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!picked) return;
    add.mutate(
      {
        ad_object_guid: picked.ad_object_guid,
        valid_from: new Date(validFrom).toISOString(),
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
          <DialogTitle>{t("classes.add_student_title")}</DialogTitle>
          <DialogDescription>{t("classes.add_student_description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {add.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {add.error.status === 409 && add.error.code === "overlapping_membership"
                ? t("classes.error_overlapping")
                : t("errors.generic")}
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="student-search">{t("classes.search_student")}</Label>
            <Input
              id="student-search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPicked(null);
              }}
              placeholder={t("users.search_placeholder")}
            />
            {search.length >= 2 && users.data ? (
              <ul className="max-h-40 overflow-y-auto rounded-md border bg-background text-sm">
                {users.data.items.length === 0 ? (
                  <li className="px-3 py-2 text-muted-foreground">{t("users.empty")}</li>
                ) : (
                  users.data.items.map((u) => (
                    <li key={u.ad_object_guid}>
                      <button
                        type="button"
                        onClick={() => setPicked(u)}
                        className={`block w-full px-3 py-2 text-left hover:bg-accent ${
                          picked?.ad_object_guid === u.ad_object_guid ? "bg-accent" : ""
                        }`}
                      >
                        {u.upn}
                        {u.given_name || u.surname
                          ? ` — ${[u.given_name, u.surname].filter(Boolean).join(" ")}`
                          : ""}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
            {picked ? (
              <p className="text-xs text-muted-foreground">
                {t("classes.picked")}: <span className="font-mono">{picked.upn}</span>
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="student-valid-from">{t("classes.valid_from")}</Label>
            <Input
              id="student-valid-from"
              type="date"
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">{t("classes.mid_year_hint")}</p>
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
            <Button type="submit" disabled={!picked || add.isPending}>
              {add.isPending ? t("common.loading") : t("classes.add_student_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BulkAddStudentsModal({
  classId,
  open,
  onClose,
}: {
  classId: number;
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<AdUserOut[]>([]);
  const [validFrom, setValidFrom] = useState(today());
  const [result, setResult] = useState<BulkClassMembershipResult | null>(null);

  const users = useUsers(
    search.length >= 2 ? { kind: "student", search, limit: 10 } : { kind: "student", limit: 0 },
  );
  const bulk = useBulkAddClassMemberships(classId);

  function toggle(u: AdUserOut): void {
    setPicked((prev) =>
      prev.some((p) => p.ad_object_guid === u.ad_object_guid)
        ? prev.filter((p) => p.ad_object_guid !== u.ad_object_guid)
        : [...prev, u],
    );
  }

  function reset(): void {
    setSearch("");
    setPicked([]);
    setValidFrom(today());
    setResult(null);
    bulk.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (picked.length === 0) return;
    bulk.mutate(
      {
        students: picked.map((u) => ({
          ad_object_guid: u.ad_object_guid,
          valid_from: new Date(validFrom).toISOString(),
        })),
      },
      {
        onSuccess: (res) => {
          setResult(res);
          if (res.errors.length === 0) {
            reset();
            onClose();
          }
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
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("classes.bulk_add_title")}</DialogTitle>
          <DialogDescription>{t("classes.bulk_add_description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {result && result.errors.length > 0 && (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <p className="font-medium">{t("classes.bulk_add_partial_error")}</p>
              <ul className="mt-1 list-inside list-disc">
                {result.errors.map((err) => (
                  <li key={err.ad_object_guid} className="text-xs">
                    {err.ad_object_guid}: {err.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {bulk.isError && !result && (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t("errors.generic")}
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="bulk-student-search">{t("classes.search_student")}</Label>
            <Input
              id="bulk-student-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("users.search_placeholder")}
            />
            {search.length >= 2 && users.data ? (
              <ul className="max-h-36 overflow-y-auto rounded-md border bg-background text-sm">
                {users.data.items.length === 0 ? (
                  <li className="px-3 py-2 text-muted-foreground">{t("users.empty")}</li>
                ) : (
                  users.data.items.map((u) => {
                    const isSelected = picked.some((p) => p.ad_object_guid === u.ad_object_guid);
                    return (
                      <li key={u.ad_object_guid}>
                        <button
                          type="button"
                          onClick={() => toggle(u)}
                          className={`flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent ${isSelected ? "bg-accent/50" : ""}`}
                        >
                          <span className="text-xs">{isSelected ? "✓" : " "}</span>
                          <span>
                            {u.upn}
                            {u.given_name || u.surname
                              ? ` — ${[u.given_name, u.surname].filter(Boolean).join(" ")}`
                              : ""}
                          </span>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            ) : null}
          </div>
          {picked.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {picked.map((u) => (
                <span
                  key={u.ad_object_guid}
                  className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium"
                >
                  {u.given_name ?? u.upn}
                  <button
                    type="button"
                    onClick={() => toggle(u)}
                    className="ml-0.5 text-muted-foreground hover:text-foreground"
                    aria-label={`Remove ${u.upn}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="bulk-valid-from">{t("classes.valid_from")}</Label>
            <Input
              id="bulk-valid-from"
              type="date"
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">{t("classes.mid_year_hint")}</p>
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
            <Button type="submit" disabled={picked.length === 0 || bulk.isPending}>
              {bulk.isPending
                ? t("common.loading")
                : t("classes.bulk_add_submit", { count: picked.length })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MoveClassModal({
  classId,
  students,
  open,
  onClose,
}: {
  classId: number;
  students: ClassMembershipOut[];
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [targetClassId, setTargetClassId] = useState<number | "">("");
  const classes = useClasses();
  const qc = useQueryClient();
  const activeStudents = students.filter((s) => s.valid_to === null);

  const move = useMutation<BulkClassMembershipResult, Error, number>({
    mutationFn: (tClassId) =>
      apiFetch<BulkClassMembershipResult>(`/classes/${tClassId}/students/bulk`, {
        method: "POST",
        body: {
          students: activeStudents.map((s) => ({
            ad_object_guid: s.ad_object_guid,
            valid_from: new Date().toISOString(),
          })),
        },
      }),
    onSuccess: (_res, tClassId) => {
      qc.invalidateQueries({ queryKey: ["classes", classId, "students"] });
      qc.invalidateQueries({ queryKey: ["classes", tClassId, "students"] });
      reset();
      onClose();
    },
  });

  function reset(): void {
    setTargetClassId("");
    move.reset();
  }

  const availableClasses = (classes.data ?? []).filter(
    (c) => c.id !== classId && c.status === "active",
  );

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!targetClassId) return;
    move.mutate(Number(targetClassId));
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
          <DialogTitle>{t("classes.move_class_title")}</DialogTitle>
          <DialogDescription>
            {t("classes.move_class_description", { count: activeStudents.length })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {move.isError && (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t("errors.generic")}
            </div>
          )}
          {activeStudents.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("classes.move_class_empty")}</p>
          ) : (
            <div className="space-y-1">
              <Label htmlFor="target-class">{t("classes.move_class_target")}</Label>
              <select
                id="target-class"
                value={targetClassId}
                onChange={(e) => setTargetClassId(e.target.value ? Number(e.target.value) : "")}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                required
              >
                <option value="">{t("classes.move_class_select_placeholder")}</option>
                {availableClasses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.kuerzel ? ` (${c.kuerzel})` : ""}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{t("classes.mid_year_hint")}</p>
            </div>
          )}
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
            {activeStudents.length > 0 && (
              <Button type="submit" disabled={!targetClassId || move.isPending}>
                {move.isPending ? t("common.loading") : t("classes.move_class_submit")}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- helpers ---------------------------------------------------------------

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatIsoDate(iso: string): string {
  // The API returns ISO datetime strings; show date only in the table to
  // keep rows tight.
  return iso.slice(0, 10);
}

function teacherRoleLabel(role: ClassTeacherRole, t: (k: string) => string): string {
  switch (role) {
    case "haupt":
      return t("classes.role_haupt");
    case "co":
      return t("classes.role_co");
    case "stellvertretung":
      return t("classes.role_stellvertretung");
  }
}

// Silence TS unused-helper warnings when only a subset is exercised by tests.
export { ClassDetailPage, AssignTeacherModal, AddStudentModal };
export type { AdUserOut, ClassTeacherOut, ClassMembershipOut };
