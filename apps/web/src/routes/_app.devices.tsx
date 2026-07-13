import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useAssignDevice,
  useClasses,
  useCreateDevice,
  useDeleteDevice,
  useDevices,
  useSchools,
  useUpdateDevice,
  useUsers,
} from "@/api/hooks";
import type { DeviceAssignmentType, DeviceOut, SchoolOut, ClassOut, AdUserOut } from "@/api/types";
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
  const q = useDevices();
  const schools = useSchools();
  const classes = useClasses();
  // Load a generous page of users once to resolve person-assignment labels.
  const users = useUsers({ limit: 1000 });

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<DeviceOut | null>(null);
  const [assignTarget, setAssignTarget] = useState<DeviceOut | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeviceOut | null>(null);

  const schoolName = (id: number): string =>
    schools.data?.find((s) => s.id === id)?.name ?? String(id);
  const className = (id: number): string =>
    classes.data?.find((c) => c.id === id)?.name ?? String(id);
  const personLabel = (guid: string): string => {
    const u = users.data?.items.find((it) => it.ad_object_guid === guid);
    return u ? displayLabel(u) : guid;
  };

  function assignmentText(d: DeviceOut): string {
    if (d.assigned_person_guid) {
      return t("devices.assigned_person", { name: personLabel(d.assigned_person_guid) });
    }
    if (d.class_id !== null) {
      return t("devices.assigned_class", { name: className(d.class_id) });
    }
    if (d.school_id !== null) {
      return t("devices.assigned_school", { name: schoolName(d.school_id) });
    }
    return t("devices.free");
  }

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
              <TableHead>{t("devices.col.name")}</TableHead>
              <TableHead>{t("devices.col.type")}</TableHead>
              <TableHead>{t("devices.col.serial")}</TableHead>
              <TableHead>{t("devices.col.assignment")}</TableHead>
              <TableHead>{t("devices.col.source")}</TableHead>
              <TableHead className="text-right">{t("devices.col.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(q.data ?? []).map((d) => (
              <TableRow key={d.id}>
                <TableCell className="font-medium">{d.name}</TableCell>
                <TableCell>{d.device_type ?? "—"}</TableCell>
                <TableCell>{d.serial_number ?? "—"}</TableCell>
                <TableCell>{assignmentText(d)}</TableCell>
                <TableCell>
                  {d.source === "ad" ? t("devices.source.ad") : t("devices.source.manual")}
                </TableCell>
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

      <CreateDeviceModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <EditDeviceModal target={editTarget} onClose={() => setEditTarget(null)} />
      <AssignDeviceModal
        target={assignTarget}
        schools={schools.data ?? []}
        classes={classes.data ?? []}
        onClose={() => setAssignTarget(null)}
      />
      <DeleteDeviceDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />
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

function EditDeviceModal({
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
  const [classId, setClassId] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [search, setSearch] = useState("");
  const [hydratedId, setHydratedId] = useState<number | null>(null);
  const assign = useAssignDevice(target?.id ?? 0);
  const personResults = useUsers({ search: search.trim(), limit: 20 });

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
              <select
                aria-label={t("devices.select_person")}
                value={personGuid}
                onChange={(e) => setPersonGuid(e.target.value)}
                size={5}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {(personResults.data?.items ?? []).map((u: AdUserOut) => (
                  <option key={u.ad_object_guid} value={u.ad_object_guid}>
                    {displayLabel(u)} · {u.upn}
                  </option>
                ))}
              </select>
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

function DeleteDeviceDialog({
  target,
  onClose,
}: {
  target: DeviceOut | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const del = useDeleteDevice();

  function handleDelete(): void {
    if (!target) return;
    del.mutate(target.id, {
      onSuccess: () => {
        del.reset();
        onClose();
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
