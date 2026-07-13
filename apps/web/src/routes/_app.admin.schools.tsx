import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useCreateSchool, useDeleteSchool, useSchools, useUpdateSchool } from "@/api/hooks";
import type { SchoolOut } from "@/api/types";
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
import { mapPointUrl, mapSearchUrl, osmEmbedUrl } from "@/lib/mapLink";

export const Route = createFileRoute("/_app/admin/schools")({
  component: SchoolsPage,
});

type TFn = (key: string, opts?: Record<string, unknown>) => string;

function schoolErrorKey(err: unknown, t: TFn): string {
  if (err instanceof ApiError) {
    if (err.code === "kuerzel_conflict") return t("schools.error_kuerzel_conflict");
    if (err.code === "school_in_use") return t("schools.error_in_use");
  }
  return t("errors.generic");
}

function schoolMapUrl(s: SchoolOut): string | null {
  if (s.latitude != null && s.longitude != null) return mapPointUrl(s.latitude, s.longitude);
  return mapSearchUrl([s.street, s.postal_code, s.city, s.name]);
}

function SchoolsPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useSchools();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SchoolOut | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SchoolOut | null>(null);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-2xl font-semibold">{t("schools.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("schools.subtitle")}</p>
        </div>
        <Button type="button" onClick={() => setCreateOpen(true)}>
          {t("schools.create_button")}
        </Button>
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : (q.data ?? []).length === 0 ? (
        <p className="text-muted-foreground">{t("schools.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("schools.col.name")}</TableHead>
              <TableHead>{t("schools.col.kuerzel")}</TableHead>
              <TableHead>{t("schools.col.city")}</TableHead>
              <TableHead>{t("schools.col.phone")}</TableHead>
              <TableHead className="text-right">{t("schools.col.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(q.data ?? []).map((s) => {
              const mapUrl = schoolMapUrl(s);
              return (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>{s.kuerzel}</TableCell>
                  <TableCell>{[s.postal_code, s.city].filter(Boolean).join(" ") || "—"}</TableCell>
                  <TableCell>{s.phone ?? "—"}</TableCell>
                  <TableCell className="space-x-2 text-right">
                    {mapUrl ? (
                      <a
                        href={mapUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-primary hover:underline"
                      >
                        {t("schools.map_open")}
                      </a>
                    ) : null}
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setEditTarget(s)}
                    >
                      {t("schools.edit_button")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={() => setDeleteTarget(s)}
                    >
                      {t("schools.delete_button")}
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <SchoolModal open={createOpen} target={null} onClose={() => setCreateOpen(false)} />
      <SchoolModal
        open={editTarget !== null}
        target={editTarget}
        onClose={() => setEditTarget(null)}
      />
      <DeleteSchoolDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </div>
  );
}

interface FormState {
  name: string;
  kuerzel: string;
  scope_short: string;
  street: string;
  postal_code: string;
  city: string;
  phone: string;
  description: string;
  latitude: string;
  longitude: string;
}

function emptyForm(): FormState {
  return {
    name: "",
    kuerzel: "",
    scope_short: "",
    street: "",
    postal_code: "",
    city: "",
    phone: "",
    description: "",
    latitude: "",
    longitude: "",
  };
}

function fromSchool(s: SchoolOut): FormState {
  return {
    name: s.name,
    kuerzel: s.kuerzel,
    scope_short: s.scope_short,
    street: s.street ?? "",
    postal_code: s.postal_code ?? "",
    city: s.city ?? "",
    phone: s.phone ?? "",
    description: s.description ?? "",
    latitude: s.latitude != null ? String(s.latitude) : "",
    longitude: s.longitude != null ? String(s.longitude) : "",
  };
}

export function SchoolModal({
  open,
  target,
  onClose,
}: {
  open: boolean;
  target: SchoolOut | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(emptyForm());
  const [hydratedId, setHydratedId] = useState<number | null>(null);
  const create = useCreateSchool();
  const update = useUpdateSchool(target?.id ?? 0);
  const mut = target ? update : create;

  // Hydrate when a new target (or the create form) opens.
  const wantId = target?.id ?? 0;
  if (open && hydratedId !== wantId) {
    setForm(target ? fromSchool(target) : emptyForm());
    setHydratedId(wantId);
    create.reset();
    update.reset();
  }

  function set<K extends keyof FormState>(key: K, value: string): void {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function close(): void {
    setHydratedId(null);
    onClose();
  }

  function numOrNull(v: string): number | null {
    const trimmed = v.trim();
    if (trimmed === "") return null;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : null;
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const body = {
      name: form.name,
      kuerzel: form.kuerzel,
      scope_short: form.scope_short,
      street: form.street || null,
      postal_code: form.postal_code || null,
      city: form.city || null,
      phone: form.phone || null,
      description: form.description || null,
      latitude: numOrNull(form.latitude),
      longitude: numOrNull(form.longitude),
    };
    if (target) {
      update.mutate(body, { onSuccess: close });
    } else {
      create.mutate(body, { onSuccess: close });
    }
  }

  const lat = numOrNull(form.latitude);
  const lon = numOrNull(form.longitude);

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? close() : undefined)}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{target ? t("schools.edit_title") : t("schools.create_title")}</DialogTitle>
          <DialogDescription>{t("schools.form_hint")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {mut.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {schoolErrorKey(mut.error, t)}
            </div>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="school-name">{t("schools.field.name")}</Label>
            <Input
              id="school-name"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              required
              maxLength={200}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="school-kuerzel">{t("schools.field.kuerzel")}</Label>
              <Input
                id="school-kuerzel"
                value={form.kuerzel}
                onChange={(e) => set("kuerzel", e.target.value)}
                required
                maxLength={50}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="school-scope">{t("schools.field.scope_short")}</Label>
              <Input
                id="school-scope"
                value={form.scope_short}
                onChange={(e) => set("scope_short", e.target.value)}
                required
                maxLength={50}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="school-street">{t("schools.field.street")}</Label>
            <Input
              id="school-street"
              value={form.street}
              onChange={(e) => set("street", e.target.value)}
              maxLength={200}
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label htmlFor="school-plz">{t("schools.field.postal_code")}</Label>
              <Input
                id="school-plz"
                value={form.postal_code}
                onChange={(e) => set("postal_code", e.target.value)}
                maxLength={20}
              />
            </div>
            <div className="col-span-2 space-y-1">
              <Label htmlFor="school-city">{t("schools.field.city")}</Label>
              <Input
                id="school-city"
                value={form.city}
                onChange={(e) => set("city", e.target.value)}
                maxLength={120}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="school-phone">{t("schools.field.phone")}</Label>
            <Input
              id="school-phone"
              value={form.phone}
              onChange={(e) => set("phone", e.target.value)}
              maxLength={50}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="school-desc">{t("schools.field.description")}</Label>
            <textarea
              id="school-desc"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              maxLength={4000}
              rows={2}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="school-lat">{t("schools.field.latitude")}</Label>
              <Input
                id="school-lat"
                value={form.latitude}
                onChange={(e) => set("latitude", e.target.value)}
                inputMode="decimal"
                placeholder="46.9480"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="school-lon">{t("schools.field.longitude")}</Label>
              <Input
                id="school-lon"
                value={form.longitude}
                onChange={(e) => set("longitude", e.target.value)}
                inputMode="decimal"
                placeholder="7.4474"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("schools.coords_hint")}</p>

          {lat != null && lon != null ? (
            <div className="space-y-1">
              <span className="text-sm font-medium">{t("schools.map_preview")}</span>
              <iframe
                title={t("schools.map_preview")}
                src={osmEmbedUrl(lat, lon)}
                className="h-56 w-full rounded-md border"
                loading="lazy"
              />
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={mut.isPending}>
              {mut.isPending ? t("common.loading") : t("schools.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteSchoolDialog({
  target,
  onClose,
}: {
  target: SchoolOut | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const del = useDeleteSchool();

  function handleDelete(): void {
    if (!target) return;
    del.mutate(target.id, {
      onSuccess: () => {
        del.reset();
        onClose();
      },
    });
  }

  return (
    <Dialog open={target !== null} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("schools.delete_title")}</DialogTitle>
          <DialogDescription>
            {target ? t("schools.delete_confirm", { name: target.name }) : ""}
          </DialogDescription>
        </DialogHeader>
        {del.isError ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {schoolErrorKey(del.error, t)}
          </div>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleDelete}
            disabled={del.isPending}
          >
            {del.isPending ? t("common.loading") : t("schools.delete_confirm_button")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
