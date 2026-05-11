import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useArchiveClass,
  useClasses,
  useCreateClass,
  useCurrentUser,
  useUpdateClass,
} from "@/api/hooks";
import type { ClassOut } from "@/api/types";
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

export const Route = createFileRoute("/_app/classes")({
  component: ClassesPage,
});

function ClassesPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useClasses();
  const me = useCurrentUser();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ClassOut | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<ClassOut | null>(null);

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
            {(q.data ?? []).map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium">
                  <Link
                    to="/classes/$classId"
                    params={{ classId: String(c.id) }}
                    className="underline-offset-2 hover:underline"
                  >
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>{c.kuerzel ?? "–"}</TableCell>
                <TableCell>{c.jahrgangsstufe}</TableCell>
                <TableCell>{c.school_id}</TableCell>
                <TableCell>
                  {c.status === "active"
                    ? t("classes.status_active")
                    : t("classes.status_archived")}
                </TableCell>
                {canWrite ? (
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setEditTarget(c)}
                      >
                        {t("classes.rename_button")}
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

      <CreateClassModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        defaultSchoolId={me.data?.school_scope[0] ?? null}
        isAdmin={me.data?.is_admin ?? false}
      />
      <RenameClassModal target={editTarget} onClose={() => setEditTarget(null)} />
      <ArchiveClassDialog target={archiveTarget} onClose={() => setArchiveTarget(null)} />
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
  const [schoolId, setSchoolId] = useState(defaultSchoolId !== null ? String(defaultSchoolId) : "");
  const create = useCreateClass();

  function reset(): void {
    setName("");
    setKuerzel("");
    setJahrgangsstufe("");
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
          <div className="space-y-1">
            <Label htmlFor="class-jahrgang">{t("classes.jahrgangsstufe")}</Label>
            <Input
              id="class-jahrgang"
              type="number"
              min={1}
              max={13}
              value={jahrgangsstufe}
              onChange={(e) => setJahrgangsstufe(e.target.value)}
              required
            />
          </div>
          {isAdmin ? (
            <div className="space-y-1">
              <Label htmlFor="class-school-id">{t("classes.school_id_label")}</Label>
              <Input
                id="class-school-id"
                type="number"
                min={1}
                value={schoolId}
                onChange={(e) => setSchoolId(e.target.value)}
                required
              />
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

export function RenameClassModal({ target, onClose }: RenameProps): JSX.Element {
  const { t } = useTranslation();
  const [name, setName] = useState(target?.name ?? "");
  const [kuerzel, setKuerzel] = useState(target?.kuerzel ?? "");
  const update = useUpdateClass(target?.id ?? 0);

  // Reset form when the modal switches between targets.
  if (target && (name === "" || name !== target.name)) {
    // No-op: state synced via the controlled inputs after the user types.
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!target) return;
    update.mutate(
      {
        ...(name !== target.name && { name }),
        ...(kuerzel !== (target.kuerzel ?? "") && { kuerzel: kuerzel || null }),
      },
      {
        onSuccess: () => onClose(),
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
          <DialogTitle>{t("classes.rename_title")}</DialogTitle>
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
            <Label htmlFor="rename-name">{t("classes.name")}</Label>
            <Input
              id="rename-name"
              defaultValue={target?.name ?? ""}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={64}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rename-kuerzel">{t("classes.kuerzel")}</Label>
            <Input
              id="rename-kuerzel"
              defaultValue={target?.kuerzel ?? ""}
              onChange={(e) => setKuerzel(e.target.value)}
              maxLength={32}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? t("common.loading") : t("classes.rename_submit")}
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

function classErrorKey(err: ApiError, t: (key: string) => string): string {
  if (err.status === 403) return t("errors.forbidden");
  if (err.status === 404 && err.code === "class_not_found") return t("classes.error_not_found");
  if (err.status === 400 && err.code === "school_id_required_for_admin")
    return t("classes.error_school_id_required");
  if (err.status === 400 && err.code === "cross_school_write") return t("errors.forbidden");
  return t("errors.generic");
}
