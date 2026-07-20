import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useAssignDevice,
  useClasses,
  useCreateDevice,
  useDeleteDevice,
  useDeviceHistory,
  useDevices,
  useSchools,
  useUpdateDevice,
  useUser,
  useUsers,
} from "@/api/hooks";
import type {
  DeviceAssignmentOut,
  DeviceAssignmentType,
  DeviceOut,
  SchoolOut,
  ClassOut,
  AdUserOut,
} from "@/api/types";
import { useFormatters } from "@/lib/useFormatters";
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
import { usePagedList } from "@/lib/usePagedList";
import { useSortable } from "@/lib/useSortable";
import { SortableHead } from "@/components/SortableHead";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/devices")({
  component: DevicesPage,
});

type TFn = (key: string, opts?: Record<string, unknown>) => string;

function deviceErrorKey(err: unknown, t: TFn): string {
  if (err instanceof ApiError) {
    if (err.status === 403 || err.code === "school_out_of_scope") {
      return t("devices.error.out_of_scope");
    }
    if (err.code.endsWith("_required") || err.code.endsWith("_not_found")) {
      return t("devices.error.assignment_invalid");
    }
  }
  return t("errors.generic");
}

function DevicesPage(): JSX.Element {
  const { t } = useTranslation();
  const childMatches = useChildMatches();
  const q = useDevices();
  const schools = useSchools();
  const classes = useClasses();

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<DeviceOut | null>(null);
  const [assignTarget, setAssignTarget] = useState<DeviceOut | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeviceOut | null>(null);
  const [historyTarget, setHistoryTarget] = useState<DeviceOut | null>(null);

  const schoolName = (id: number): string =>
    schools.data?.find((s) => s.id === id)?.name ?? String(id);
  const className = (id: number): string =>
    classes.data?.find((c) => c.id === id)?.name ?? String(id);

  function assignmentText(d: DeviceOut): string {
    if (d.assigned_person_guid) {
      const name = d.assigned_person_name ?? d.assigned_person_guid;
      const base = t("devices.assigned_person", { name });
      return d.is_loan ? `${base} · ${t("devices.loan_badge")}` : base;
    }
    if (d.class_id !== null) {
      return t("devices.assigned_class", { name: className(d.class_id) });
    }
    if (d.school_id !== null) {
      return t("devices.assigned_school", { name: schoolName(d.school_id) });
    }
    return t("devices.free");
  }

  const sourceText = (d: DeviceOut): string =>
    d.source === "ad" ? t("devices.source.ad") : t("devices.source.manual");

  const { sorted, sort, toggle } = useSortable(
    q.data ?? [],
    {
      name: (d) => d.name,
      type: (d) => d.device_type,
      serial: (d) => d.serial_number,
      assignment: (d) => assignmentText(d),
      source: (d) => sourceText(d),
    },
    "name",
  );
  const paged = usePagedList(sorted);

  // A child route (/devices/$deviceId) takes over the whole panel.
  if (childMatches.length > 0) return <Outlet />;

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-2xl font-semibold">{t("devices.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("devices.subtitle")}</p>
        </div>
        <Button type="button" onClick={() => setCreateOpen(true)}>
          {t("devices.create_button")}
        </Button>
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : (q.data ?? []).length === 0 ? (
        <p className="text-muted-foreground">{t("devices.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <SortableHead sortKey="name" sort={sort} onSort={toggle}>
                {t("devices.col.name")}
              </SortableHead>
              <SortableHead sortKey="type" sort={sort} onSort={toggle}>
                {t("devices.col.type")}
              </SortableHead>
              <SortableHead sortKey="serial" sort={sort} onSort={toggle}>
                {t("devices.col.serial")}
              </SortableHead>
              <SortableHead sortKey="assignment" sort={sort} onSort={toggle}>
                {t("devices.col.assignment")}
              </SortableHead>
              <SortableHead sortKey="source" sort={sort} onSort={toggle}>
                {t("devices.col.source")}
              </SortableHead>
              <TableHead className="text-right">{t("devices.col.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paged.pageItems.map((d) => (
              <TableRow key={d.id}>
                <TableCell className="p-0 font-medium">
                  <Link
                    to="/devices/$deviceId"
                    params={{ deviceId: String(d.id) }}
                    className="block px-4 py-3 text-primary underline-offset-2 hover:underline"
                  >
                    {d.name}
                  </Link>
                </TableCell>
                <TableCell>{d.device_type ?? "—"}</TableCell>
                <TableCell>{d.serial_number ?? "—"}</TableCell>
                <TableCell>{assignmentText(d)}</TableCell>
                <TableCell>{sourceText(d)}</TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setAssignTarget(d)}
                  >
                    {t("devices.assign_button")}
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setEditTarget(d)}>
                    {t("devices.edit_button")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setHistoryTarget(d)}
                  >
                    {t("devices.history_button")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => setDeleteTarget(d)}
                  >
                    {t("devices.delete_button")}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!q.isLoading && !q.isError ? <Pagination paged={paged} /> : null}

      <CreateDeviceModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <EditDeviceModal target={editTarget} onClose={() => setEditTarget(null)} />
      <AssignDeviceModal
        target={assignTarget}
        schools={schools.data ?? []}
        classes={classes.data ?? []}
        onClose={() => setAssignTarget(null)}
      />
      <DeleteDeviceDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />
      <DeviceHistoryModal target={historyTarget} onClose={() => setHistoryTarget(null)} />
    </div>
  );
}

interface DeviceFieldProps {
  name: string;
  setName: (v: string) => void;
  deviceType: string;
  setDeviceType: (v: string) => void;
  serial: string;
  setSerial: (v: string) => void;
  notes: string;
  setNotes: (v: string) => void;
}

function DeviceFields(props: DeviceFieldProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <>
      <div className="space-y-1">
        <Label htmlFor="device-name">{t("devices.field.name")}</Label>
        <Input
          id="device-name"
          value={props.name}
          onChange={(e) => props.setName(e.target.value)}
          required
          maxLength={255}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="device-type">{t("devices.field.type")}</Label>
        <Input
          id="device-type"
          value={props.deviceType}
          onChange={(e) => props.setDeviceType(e.target.value)}
          maxLength={64}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="device-serial">{t("devices.field.serial")}</Label>
        <Input
          id="device-serial"
          value={props.serial}
          onChange={(e) => props.setSerial(e.target.value)}
          maxLength={128}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="device-notes">{t("devices.field.notes")}</Label>
        <textarea
          id="device-notes"
          value={props.notes}
          onChange={(e) => props.setNotes(e.target.value)}
          maxLength={4000}
          rows={2}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        />
      </div>
    </>
  );
}

export function CreateDeviceModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [serial, setSerial] = useState("");
  const [notes, setNotes] = useState("");
  const create = useCreateDevice();

  function reset(): void {
    setName("");
    setDeviceType("");
    setSerial("");
    setNotes("");
    create.reset();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    create.mutate(
      {
        name,
        device_type: deviceType || null,
        serial_number: serial || null,
        notes: notes || null,
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
          <DialogTitle>{t("devices.create_title")}</DialogTitle>
          <DialogDescription>{t("devices.create_description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {create.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {deviceErrorKey(create.error, t)}
            </div>
          ) : null}
          <DeviceFields
            name={name}
            setName={setName}
            deviceType={deviceType}
            setDeviceType={setDeviceType}
            serial={serial}
            setSerial={setSerial}
            notes={notes}
            setNotes={setNotes}
          />
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
              {create.isPending ? t("common.loading") : t("devices.create_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EditDeviceModal({
  target,
  onClose,
}: {
  target: DeviceOut | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [serial, setSerial] = useState("");
  const [notes, setNotes] = useState("");
  const update = useUpdateDevice(target?.id ?? 0);
  const [hydratedId, setHydratedId] = useState<number | null>(null);

  // Hydrate the form when a new target opens.
  if (target && hydratedId !== target.id) {
    setName(target.name);
    setDeviceType(target.device_type ?? "");
    setSerial(target.serial_number ?? "");
    setNotes(target.notes ?? "");
    setHydratedId(target.id);
    update.reset();
  }

  function close(): void {
    setHydratedId(null);
    onClose();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    update.mutate(
      {
        name,
        device_type: deviceType,
        serial_number: serial,
        notes,
      },
      { onSuccess: close },
    );
  }

  return (
    <Dialog open={target !== null} onOpenChange={(next) => (!next ? close() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("devices.edit_title")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {update.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {deviceErrorKey(update.error, t)}
            </div>
          ) : null}
          <DeviceFields
            name={name}
            setName={setName}
            deviceType={deviceType}
            setDeviceType={setDeviceType}
            serial={serial}
            setSerial={setSerial}
            notes={notes}
            setNotes={setNotes}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? t("common.loading") : t("devices.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AssignDeviceModal({
  target,
  schools,
  classes,
  onClose,
}: {
  target: DeviceOut | null;
  schools: SchoolOut[];
  classes: ClassOut[];
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [type, setType] = useState<DeviceAssignmentType>("free");
  const [personGuid, setPersonGuid] = useState("");
  const [personLabel, setPersonLabel] = useState("");
  const [isLoan, setIsLoan] = useState(false);
  const [classId, setClassId] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [search, setSearch] = useState("");
  const [hydratedId, setHydratedId] = useState<number | null>(null);
  const assign = useAssignDevice(target?.id ?? 0);
  // keepPrevious so the list doesn't blank while typing (a click can't land on
  // an empty list); limit generous but capped — a hint nudges to search.
  const personResults = useUsers({ search: search.trim(), limit: 25 }, { keepPrevious: true });
  // Resolve the *currently assigned* person by GUID directly, so the pinned row
  // always shows a name even when the device payload's assigned_person_name is
  // null (e.g. resolved from a stale cache) — never a raw GUID.
  const assignedUser = useUser(target?.assigned_person_guid ?? "");

  if (target && hydratedId !== target.id) {
    setType(
      target.assigned_person_guid
        ? "person"
        : target.class_id !== null
          ? "class"
          : target.school_id !== null
            ? "school"
            : "free",
    );
    setPersonGuid(target.assigned_person_guid ?? "");
    setPersonLabel(target.assigned_person_name ?? "");
    setIsLoan(target.is_loan);
    setClassId(target.class_id !== null ? String(target.class_id) : "");
    setSchoolId(target.school_id !== null ? String(target.school_id) : "");
    setSearch("");
    setHydratedId(target.id);
    assign.reset();
  }

  function close(): void {
    setHydratedId(null);
    onClose();
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    assign.mutate(
      {
        assignment_type: type,
        person_guid: type === "person" ? personGuid : null,
        class_id: type === "class" && classId ? Number(classId) : null,
        school_id: type === "school" && schoolId ? Number(schoolId) : null,
        is_loan: type === "person" ? isLoan : false,
      },
      { onSuccess: close },
    );
  }

  const submitDisabled =
    assign.isPending ||
    (type === "person" && !personGuid) ||
    (type === "class" && !classId) ||
    (type === "school" && !schoolId);

  return (
    <Dialog open={target !== null} onOpenChange={(next) => (!next ? close() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("devices.assign_title")}</DialogTitle>
          <DialogDescription>{target?.name}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {assign.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {deviceErrorKey(assign.error, t)}
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="assign-type">{t("devices.assignment_type")}</Label>
            <select
              id="assign-type"
              value={type}
              onChange={(e) => setType(e.target.value as DeviceAssignmentType)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="free">{t("devices.assignment.free")}</option>
              <option value="person">{t("devices.assignment.person")}</option>
              <option value="class">{t("devices.assignment.class")}</option>
              <option value="school">{t("devices.assignment.school")}</option>
            </select>
          </div>

          {type === "person" ? (
            <div className="space-y-1">
              <Label htmlFor="assign-person-search">{t("devices.select_person")}</Label>
              <Input
                id="assign-person-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("devices.person_search_placeholder")}
              />
              {(() => {
                const items = personResults.data?.items ?? [];
                const total = personResults.data?.total ?? items.length;
                const selectedInList = items.some((u) => u.ad_object_guid === personGuid);
                // Prefer the label captured on selection; else the freshly
                // resolved user; else the seeded name; only the GUID as a last
                // resort (which the resolution above is designed to avoid).
                const pinnedLabel =
                  personLabel ||
                  (assignedUser.data && assignedUser.data.ad_object_guid === personGuid
                    ? `${displayLabel(assignedUser.data)} · ${assignedUser.data.upn}`
                    : "") ||
                  personGuid;
                return (
                  <>
                    {/* Currently-selected person stays pinned + visible even when
                        filtered out of the results, so a selection is never lost. */}
                    {personGuid && !selectedInList ? (
                      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                        <input
                          type="radio"
                          name="assign-person"
                          checked
                          readOnly
                          className="h-4 w-4"
                        />
                        <span className="min-w-0 truncate">
                          {pinnedLabel}
                          <span className="ml-1 text-xs text-muted-foreground">
                            ({t("devices.person_selected")})
                          </span>
                        </span>
                      </div>
                    ) : null}
                    <div
                      role="radiogroup"
                      aria-label={t("devices.select_person")}
                      className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2"
                    >
                      {items.length === 0 ? (
                        <p className="px-1 py-2 text-xs text-muted-foreground">
                          {t("devices.person_no_results")}
                        </p>
                      ) : (
                        items.map((u: AdUserOut) => (
                          <label key={u.ad_object_guid} className="flex items-start gap-2 text-sm">
                            <input
                              type="radio"
                              name="assign-person"
                              className="mt-0.5 h-4 w-4"
                              checked={personGuid === u.ad_object_guid}
                              onChange={() => {
                                setPersonGuid(u.ad_object_guid);
                                setPersonLabel(`${displayLabel(u)} · ${u.upn}`);
                              }}
                            />
                            <span className="min-w-0">
                              <span className="font-medium">{displayLabel(u)}</span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {u.upn}
                              </span>
                            </span>
                          </label>
                        ))
                      )}
                    </div>
                    {total > items.length ? (
                      <p className="text-xs text-muted-foreground">
                        {t("devices.person_more_hint", { shown: items.length, total })}
                      </p>
                    ) : null}
                  </>
                );
              })()}
              <label className="mt-2 flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={isLoan}
                  onChange={(e) => setIsLoan(e.target.checked)}
                />
                <span>
                  {t("devices.is_loan")}
                  <span className="block text-xs text-muted-foreground">
                    {t("devices.is_loan_hint")}
                  </span>
                </span>
              </label>
            </div>
          ) : null}

          {type === "class" ? (
            <div className="space-y-1">
              <Label htmlFor="assign-class">{t("devices.select_class")}</Label>
              <select
                id="assign-class"
                value={classId}
                onChange={(e) => setClassId(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">{t("devices.select_placeholder")}</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {type === "school" ? (
            <div className="space-y-1">
              <Label htmlFor="assign-school">{t("devices.select_school")}</Label>
              <select
                id="assign-school"
                value={schoolId}
                onChange={(e) => setSchoolId(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">{t("devices.select_placeholder")}</option>
                {schools.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.kuerzel})
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={submitDisabled}>
              {assign.isPending ? t("common.loading") : t("devices.assign_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DeleteDeviceDialog({
  target,
  onClose,
  onDeleted,
}: {
  target: DeviceOut | null;
  onClose: () => void;
  onDeleted?: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const del = useDeleteDevice();

  function handleDelete(): void {
    if (!target) return;
    del.mutate(target.id, {
      onSuccess: () => {
        del.reset();
        onClose();
        onDeleted?.();
      },
    });
  }

  const description = target ? t("devices.delete_confirm", { name: target.name }) : "";

  return (
    <Dialog open={target !== null} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("devices.delete_title")}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {del.isError ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {deviceErrorKey(del.error, t)}
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
            {del.isPending ? t("common.loading") : t("devices.delete_confirm_button")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeviceHistoryModal({
  target,
  onClose,
}: {
  target: DeviceOut | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const fmt = useFormatters();
  const history = useDeviceHistory(target?.id ?? null);

  const assignmentTypeLabel = (type: DeviceAssignmentOut["assignment_type"]): string => {
    if (type === "person") return t("devices.history_type.person");
    if (type === "class") return t("devices.history_type.class");
    return t("devices.history_type.school");
  };

  return (
    <Dialog open={target !== null} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("devices.history_title")}</DialogTitle>
          <DialogDescription>{target?.name ?? ""}</DialogDescription>
        </DialogHeader>
        {history.isLoading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : history.isError ? (
          <p className="text-sm text-destructive">{t("errors.generic")}</p>
        ) : (history.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("devices.history_empty")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("devices.history_col.holder")}</TableHead>
                <TableHead>{t("devices.history_col.type")}</TableHead>
                <TableHead>{t("devices.history_col.period")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(history.data ?? []).map((h) => (
                <TableRow key={h.id}>
                  <TableCell className="font-medium">
                    {h.label || "—"}
                    {h.is_loan ? (
                      <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                        {t("devices.loan_badge")}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>{assignmentTypeLabel(h.assignment_type)}</TableCell>
                  <TableCell>
                    {fmt.formatDateTime(h.valid_from)} –{" "}
                    {h.valid_to ? (
                      fmt.formatDateTime(h.valid_to)
                    ) : (
                      <span className="text-muted-foreground">{t("devices.history_ongoing")}</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
