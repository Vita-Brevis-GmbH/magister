import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useClasses,
  useDevice,
  useDeviceHistory,
  useNinjaStatus,
  useRunNinjaScript,
  useSchools,
} from "@/api/hooks";
import type { DeviceAssignmentOut, DeviceOut } from "@/api/types";
import {
  AssignDeviceModal,
  DeleteDeviceDialog,
  EditDeviceModal,
  UnassignButton,
} from "@/routes/_app.devices";
import { useTerms } from "@/lib/useTerms";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useFormatters } from "@/lib/useFormatters";

export const Route = createFileRoute("/_app/devices/$deviceId")({
  component: DeviceDetailPage,
});

/** One label/value row, mirroring the user-detail layout. */
function InfoRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="flex gap-3 py-1 text-sm">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className="font-medium">{children}</span>
    </div>
  );
}

function DeviceDetailPage(): JSX.Element {
  const { t } = useTranslation();
  const { tt } = useTerms();
  const navigate = useNavigate();
  const { deviceId } = Route.useParams();
  const id = Number(deviceId);
  const q = useDevice(Number.isNaN(id) ? null : id);
  const schools = useSchools();
  const classes = useClasses();
  const history = useDeviceHistory(Number.isNaN(id) ? null : id);
  const fmt = useFormatters();

  const [editOpen, setEditOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const backLink = (
    <Link to="/devices" className="text-sm text-muted-foreground hover:underline">
      ← {t("devices.title")}
    </Link>
  );

  if (q.isLoading) {
    return (
      <div className="space-y-4">
        {backLink}
        <p>{t("common.loading")}</p>
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="space-y-4">
        {backLink}
        <p className="text-destructive">{t("devices.detail.not_found")}</p>
      </div>
    );
  }

  const device = q.data;
  const schoolName = (sid: number): string =>
    schools.data?.find((s) => s.id === sid)?.name ?? String(sid);
  const className = (cid: number): string =>
    classes.data?.find((c) => c.id === cid)?.name ?? String(cid);

  const assignmentText = (d: DeviceOut): string => {
    if (d.assigned_person_guid) {
      return d.assigned_person_name ?? d.assigned_person_guid;
    }
    if (d.class_id !== null) return t("devices.assigned_class", { name: className(d.class_id) });
    if (d.school_id !== null)
      return tt("devices.assigned_school", { name: schoolName(d.school_id) });
    return t("devices.free");
  };

  const assignmentTypeLabel = (type: DeviceAssignmentOut["assignment_type"]): string => {
    if (type === "person") return t("devices.history_type.person");
    if (type === "class") return t("devices.history_type.class");
    return tt("devices.history_type.school");
  };

  return (
    <div className="space-y-6">
      {backLink}

      {/* Header */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="font-serif text-2xl">{device.name}</CardTitle>
            <p className="text-sm text-muted-foreground">
              {device.source === "ad" ? t("devices.source.ad") : t("devices.source.manual")}
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setAssignOpen(true)}>
              {t("devices.assign_button")}
            </Button>
            <Button type="button" variant="outline" onClick={() => setEditOpen(true)}>
              {t("devices.edit_button")}
            </Button>
            <Button type="button" variant="destructive" onClick={() => setDeleteOpen(true)}>
              {t("devices.delete_button")}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {/* Details */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("devices.detail.details_title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <InfoRow label={t("devices.field.name")}>{device.name}</InfoRow>
          <InfoRow label={t("devices.field.type")}>{device.device_type ?? "—"}</InfoRow>
          <InfoRow label={t("devices.field.serial")}>{device.serial_number ?? "—"}</InfoRow>
          <InfoRow label={t("devices.field.notes")}>{device.notes ?? "—"}</InfoRow>
          <InfoRow label={t("devices.col.source")}>
            {device.source === "ad" ? t("devices.source.ad") : t("devices.source.manual")}
          </InfoRow>
          {device.ad_object_guid ? (
            <InfoRow label={t("devices.detail.ad_guid")}>
              <span className="font-mono text-xs">{device.ad_object_guid}</span>
            </InfoRow>
          ) : null}
          <InfoRow label={t("devices.detail.created_at")}>
            {fmt.formatDateTime(device.created_at)}
          </InfoRow>
          <InfoRow label={t("devices.detail.updated_at")}>
            {fmt.formatDateTime(device.updated_at)}
          </InfoRow>
        </CardContent>
      </Card>

      {/* Assignment */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-base">{t("devices.detail.assignment_title")}</CardTitle>
          <div className="flex gap-2">
            <UnassignButton device={device} variant="outline" />
            <Button type="button" size="sm" variant="outline" onClick={() => setAssignOpen(true)}>
              {t("devices.assign_button")}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm">
            <span className="font-medium">{assignmentText(device)}</span>
            {device.is_loan ? (
              <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                {t("devices.loan_badge")}
              </span>
            ) : null}
          </p>
        </CardContent>
      </Card>

      {/* History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("devices.history_title")}</CardTitle>
        </CardHeader>
        <CardContent>
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
                        <span className="text-muted-foreground">
                          {t("devices.history_ongoing")}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <NinjaPanel deviceId={id} deviceName={device.name} />

      <EditDeviceModal target={editOpen ? device : null} onClose={() => setEditOpen(false)} />
      <AssignDeviceModal
        target={assignOpen ? device : null}
        schools={schools.data ?? []}
        classes={classes.data ?? []}
        onClose={() => setAssignOpen(false)}
      />
      <DeleteDeviceDialog
        target={deleteOpen ? device : null}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => navigate({ to: "/devices" })}
      />
    </div>
  );
}

const selectClasses =
  "flex h-10 w-56 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

function NinjaOnlineBadge({ offline }: { offline: boolean | null }): JSX.Element {
  const { t } = useTranslation();
  if (offline === null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`h-2 w-2 rounded-full ${offline ? "bg-muted-foreground/50" : "bg-emerald-500"}`}
      />
      {offline ? t("devices.ninja.offline") : t("devices.ninja.online")}
    </span>
  );
}

/** NinjaOne panel — lives ONLY on the device detail view. Everything is live:
 *  the status/scripts come from one read call and are never persisted, and a
 *  script run is re-matched server-side. Renders nothing when the connector is
 *  not configured. */
function NinjaPanel({
  deviceId,
  deviceName,
}: {
  deviceId: number;
  deviceName: string;
}): JSX.Element | null {
  const { t } = useTranslation();
  const fmt = useFormatters();
  const q = useNinjaStatus(deviceId);
  const run = useRunNinjaScript(deviceId);
  const [scriptId, setScriptId] = useState("");
  const [params, setParams] = useState("");
  const [confirming, setConfirming] = useState(false);

  // Connector off (or status not known yet) → no NinjaOne section at all.
  if (!q.data || !q.data.enabled) return null;
  const data = q.data;
  const s = data.status;
  const canRun = scriptId.trim() !== "" && !Number.isNaN(Number(scriptId));

  function submit(): void {
    if (!canRun) return;
    run.mutate(
      { script_id: Number(scriptId), parameters: params.trim() || null },
      {
        onSuccess: () => {
          setConfirming(false);
          setParams("");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("devices.ninja.section_title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.error ? (
          <p className="text-sm text-muted-foreground">{t("devices.ninja.error")}</p>
        ) : !data.matched ? (
          <p className="text-sm text-muted-foreground">
            {data.ambiguous ? t("devices.ninja.ambiguous") : t("devices.ninja.not_matched")}
          </p>
        ) : (
          <>
            <div>
              <InfoRow label={t("devices.ninja.field_status")}>
                <NinjaOnlineBadge offline={s?.offline ?? null} />
              </InfoRow>
              <InfoRow label={t("devices.ninja.field_hostname")}>
                {s?.system_name ?? s?.dns_name ?? "—"}
              </InfoRow>
              <InfoRow label={t("devices.ninja.field_os")}>{s?.os_name ?? "—"}</InfoRow>
              <InfoRow label={t("devices.field.serial")}>{s?.serial_number ?? "—"}</InfoRow>
              <InfoRow label={t("devices.ninja.field_last_contact")}>
                {s?.last_contact
                  ? fmt.formatDateTime(new Date(s.last_contact * 1000).toISOString())
                  : "—"}
              </InfoRow>
            </div>

            <div className="space-y-2 border-t pt-4">
              <h3 className="text-sm font-medium">{t("devices.ninja.run_title")}</h3>
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor="ninja-script">{t("devices.ninja.run_script_label")}</Label>
                  {data.scripts.length > 0 ? (
                    <select
                      id="ninja-script"
                      className={selectClasses}
                      value={scriptId}
                      onChange={(e) => setScriptId(e.target.value)}
                    >
                      <option value="">{t("devices.ninja.run_script_placeholder")}</option>
                      {data.scripts.map((sc) => (
                        <option key={sc.id} value={sc.id}>
                          {sc.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      id="ninja-script"
                      className="w-40"
                      inputMode="numeric"
                      placeholder={t("devices.ninja.run_script_id_label")}
                      value={scriptId}
                      onChange={(e) => setScriptId(e.target.value)}
                    />
                  )}
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ninja-params">{t("devices.ninja.run_params_label")}</Label>
                  <Input
                    id="ninja-params"
                    className="w-56"
                    value={params}
                    onChange={(e) => setParams(e.target.value)}
                  />
                </div>
              </div>
              {data.scripts.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {t("devices.ninja.no_scripts_hint")}
                </p>
              ) : null}

              {confirming ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-amber-700">
                    {t("devices.ninja.run_confirm", { device: deviceName })}
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    disabled={run.isPending}
                    onClick={submit}
                  >
                    {run.isPending ? t("common.loading") : t("devices.ninja.run_confirm_yes")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setConfirming(false)}
                  >
                    {t("common.cancel")}
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!canRun}
                  onClick={() => setConfirming(true)}
                >
                  {t("devices.ninja.run_button")}
                </Button>
              )}

              {run.isSuccess ? (
                <p className="text-sm text-emerald-700">
                  {t("devices.ninja.run_ok", { id: run.data.ninja_device_id })}
                </p>
              ) : run.isError ? (
                <p className="text-sm text-destructive">{t("devices.ninja.run_error")}</p>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
