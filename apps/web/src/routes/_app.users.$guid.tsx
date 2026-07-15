import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  downloadCredentialPdf,
  saveBlob,
  useCurrentUser,
  useDeleteAdUser,
  useMailDomains,
  useUpdateUser,
  useUser,
  useUserDashboard,
} from "@/api/hooks";
import type { AdUserOut, UserAttributesUpdate, UserDashboardOut } from "@/api/types";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { SubjectAccessModal } from "@/components/SubjectAccessModal";
import { UserAvatar } from "@/components/UserAvatar";
import { UserStatusModal } from "@/components/UserStatusModal";
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
import { gradeLabel, gradeRangeLabel } from "@/lib/grade";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/users/$guid")({
  component: UserDetailPage,
});

interface FormState {
  display_name: string;
  given_name: string;
  surname: string;
  upn_local: string;
  upn_domain: string;
  sam_account_name: string;
  mail_local: string;
  mail_domain: string;
  street_address: string;
  locality: string;
  postal_code: string;
  country: string;
  temp_device_name: string;
  jahrgangsstufe: string;
  password_never_expires: boolean;
  cannot_change_password: boolean;
  store_password: boolean;
}

function emptyForm(): FormState {
  return {
    display_name: "",
    given_name: "",
    surname: "",
    upn_local: "",
    upn_domain: "",
    sam_account_name: "",
    mail_local: "",
    mail_domain: "",
    street_address: "",
    locality: "",
    postal_code: "",
    country: "",
    temp_device_name: "",
    jahrgangsstufe: "",
    password_never_expires: false,
    cannot_change_password: false,
    store_password: false,
  };
}

function splitMail(value: string | null | undefined): { local: string; domain: string } {
  if (!value) return { local: "", domain: "" };
  const [local, domain = ""] = value.split("@");
  return { local: local ?? "", domain };
}

function UserDetailPage(): JSX.Element {
  const { t, i18n } = useTranslation();
  const { guid } = Route.useParams();
  const userQ = useUser(guid);
  const dashboardQ = useUserDashboard(guid);
  const mailDomainsQ = useMailDomains();
  const me = useCurrentUser();
  const update = useUpdateUser(guid);
  const del = useDeleteAdUser();
  const navigate = useNavigate();

  const canChangeLogin = me.data?.is_admin ?? false;
  const domains = mailDomainsQ.data?.domains ?? [];

  const [form, setForm] = useState<FormState>(emptyForm);
  const [savedFlash, setSavedFlash] = useState(false);
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [pdfOpen, setPdfOpen] = useState(false);
  const [pdfHeading, setPdfHeading] = useState("");
  const [pdfBody, setPdfBody] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState(false);

  async function handleDownloadPdf(): Promise<void> {
    setPdfBusy(true);
    setPdfError(false);
    try {
      const { blob, filename } = await downloadCredentialPdf(guid, {
        custom_heading: pdfHeading.trim() || null,
        custom_body: pdfBody.trim() || null,
        language: i18n.language,
      });
      saveBlob(blob, filename);
      setPdfOpen(false);
      setPdfHeading("");
      setPdfBody("");
    } catch {
      setPdfError(true);
    } finally {
      setPdfBusy(false);
    }
  }

  // Re-hydrate the form from the loaded user. Runs on load and whenever we
  // (re-)enter edit mode, so Cancel + re-open always starts from server state.
  const hydrateForm = useCallback(() => {
    if (!userQ.data) return;
    const upn = splitMail(userQ.data.upn);
    const mail = splitMail(userQ.data.mail);
    setForm({
      display_name: userQ.data.display_name ?? "",
      given_name: userQ.data.given_name ?? "",
      surname: userQ.data.surname ?? "",
      upn_local: upn.local,
      upn_domain: upn.domain,
      sam_account_name: userQ.data.sam_account_name ?? "",
      mail_local: mail.local,
      mail_domain: mail.domain,
      street_address: userQ.data.street_address ?? "",
      locality: userQ.data.locality ?? "",
      postal_code: userQ.data.postal_code ?? "",
      country: userQ.data.country ?? "",
      temp_device_name: userQ.data.temp_device_name ?? "",
      jahrgangsstufe: userQ.data.jahrgangsstufe != null ? String(userQ.data.jahrgangsstufe) : "",
      password_never_expires: userQ.data.password_never_expires,
      cannot_change_password: userQ.data.cannot_change_password,
      store_password: userQ.data.store_password,
    });
  }, [userQ.data]);

  useEffect(() => {
    hydrateForm();
  }, [hydrateForm]);

  function startEditing(): void {
    hydrateForm();
    setSavedFlash(false);
    update.reset();
    setEditing(true);
  }

  function cancelEditing(): void {
    hydrateForm();
    update.reset();
    setEditing(false);
  }

  function setField<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSavedFlash(false);
    update.reset();
  }

  function buildPayload(): UserAttributesUpdate {
    if (!userQ.data) return {};
    const out: UserAttributesUpdate = {};
    const current = userQ.data;

    // Trim and normalise the values once.
    const trimOrNull = (v: string): string | null => (v.trim() ? v.trim() : null);

    const dn = trimOrNull(form.display_name);
    if (dn !== current.display_name) out.display_name = dn;

    const gn = trimOrNull(form.given_name);
    if (gn !== current.given_name) out.given_name = gn;
    const sn = trimOrNull(form.surname);
    if (sn !== current.surname) out.surname = sn;

    if (canChangeLogin) {
      const upnNew =
        form.upn_local.trim() && form.upn_domain
          ? `${form.upn_local.trim().toLowerCase()}@${form.upn_domain}`
          : null;
      if (upnNew && upnNew !== current.upn) out.upn = upnNew;
      const samNew = form.sam_account_name.trim() || null;
      if (samNew !== current.sam_account_name) out.sam_account_name = samNew;
    }

    const mailNew =
      form.mail_local.trim() && form.mail_domain
        ? `${form.mail_local.trim().toLowerCase()}@${form.mail_domain}`
        : null;
    if (mailNew !== current.mail) out.mail = mailNew;

    const addressFields: Array<
      "street_address" | "locality" | "postal_code" | "country" | "temp_device_name"
    > = ["street_address", "locality", "postal_code", "country", "temp_device_name"];
    for (const f of addressFields) {
      const next = trimOrNull(form[f]);
      const cur = (current as unknown as Record<string, string | null>)[f] ?? null;
      if (next !== cur) out[f] = next;
    }

    // Per-student grade (Magister-only). Blank clears it.
    const gradeNew = form.jahrgangsstufe.trim() === "" ? null : Number(form.jahrgangsstufe);
    if (gradeNew !== current.jahrgangsstufe) out.jahrgangsstufe = gradeNew;

    // AD account-policy flags.
    if (form.password_never_expires !== current.password_never_expires)
      out.password_never_expires = form.password_never_expires;
    if (form.cannot_change_password !== current.cannot_change_password)
      out.cannot_change_password = form.cannot_change_password;
    if (form.store_password !== current.store_password) out.store_password = form.store_password;

    return out;
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const payload = buildPayload();
    if (Object.keys(payload).length === 0) return;
    update.mutate(payload, {
      onSuccess: () => {
        setSavedFlash(true);
        setEditing(false);
      },
    });
  }

  if (userQ.isLoading) {
    return <UserDetailSkeleton />;
  }
  if (userQ.isError) {
    const err = userQ.error;
    if (err instanceof ApiError && err.status === 404) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>{t("users.detail.not_found_title")}</CardTitle>
            <CardDescription>{t("users.detail.not_found_desc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <BackToList />
          </CardContent>
        </Card>
      );
    }
    return <p className="text-destructive">{t("errors.generic")}</p>;
  }
  if (!userQ.data) return <></>;

  const user = userQ.data;
  const errorDetail = update.isError ? renderPatchError(update.error, t) : null;

  return (
    <div className="space-y-6">
      <BackToList />

      <Card>
        <CardHeader className="flex flex-row items-center gap-4 space-y-0">
          <UserAvatar user={user} size="lg" />
          <div className="flex-1">
            <CardTitle className="font-serif text-2xl">{displayLabel(user)}</CardTitle>
            <CardDescription className="font-mono text-xs">{user.upn}</CardDescription>
          </div>
          {user.enabled ? (
            <StatusPill tone="ok">{t("users.status_active")}</StatusPill>
          ) : (
            <StatusPill tone="muted">{t("users.status_disabled")}</StatusPill>
          )}
          {!editing ? (
            <Button type="button" variant="outline" onClick={() => setPdfOpen(true)}>
              {t("users.detail.credential_pdf")}
            </Button>
          ) : null}
          {!editing ? (
            <Button type="button" onClick={startEditing}>
              {t("users.detail.edit")}
            </Button>
          ) : null}
          {/* Step 1: (de)activate. Not for one's own account. */}
          {!editing && me.data && me.data.ad_object_guid !== guid ? (
            <Button type="button" variant="outline" onClick={() => setStatusOpen(true)}>
              {user.enabled ? t("user_status.button_disable") : t("user_status.button_enable")}
            </Button>
          ) : null}
          {/* Step 2: permanent delete — only for already-deactivated accounts. */}
          {!editing && me.data?.is_admin && !user.enabled ? (
            confirmDelete ? (
              <div className="flex items-center gap-2">
                <span className="text-sm text-destructive">
                  {t("users.detail.delete_confirm_permanent")}
                </span>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  disabled={del.isPending}
                  onClick={() => del.mutate(guid, { onSuccess: () => navigate({ to: "/users" }) })}
                >
                  {t("users.detail.delete_yes")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirmDelete(false)}
                >
                  {t("common.cancel")}
                </Button>
              </div>
            ) : (
              <Button type="button" variant="destructive" onClick={() => setConfirmDelete(true)}>
                {t("users.detail.delete_permanent")}
              </Button>
            )
          ) : null}
        </CardHeader>
      </Card>

      {del.isError ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {del.error instanceof ApiError && del.error.status === 503
            ? t("users.detail.delete_err_ad")
            : t("errors.generic")}
        </div>
      ) : null}

      {savedFlash && !editing ? (
        <div
          role="status"
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
        >
          {t("users.detail.saved")}
        </div>
      ) : null}

      {!editing ? (
        <UserReadView
          user={user}
          dashboard={dashboardQ.data}
          onOpenPrivacy={() => setPrivacyOpen(true)}
        />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-6">
          {errorDetail ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {errorDetail}
            </div>
          ) : savedFlash ? (
            <div
              role="status"
              className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
            >
              {t("users.detail.saved")}
            </div>
          ) : null}

          {/* Identität */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("users.detail.section_identity")}</CardTitle>
              <CardDescription>{t("users.detail.section_identity_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                id="display_name"
                label={t("users.field.display_name")}
                value={form.display_name}
                onChange={(v) => setField("display_name", v)}
                placeholder={t("users.field.display_name_placeholder")}
              />
              <div className="grid grid-cols-2 gap-3">
                <Field
                  id="given_name"
                  label={t("users.field.given_name")}
                  value={form.given_name}
                  onChange={(v) => setField("given_name", v)}
                />
                <Field
                  id="surname"
                  label={t("users.field.surname")}
                  value={form.surname}
                  onChange={(v) => setField("surname", v)}
                />
              </div>
              <UpnField
                localValue={form.upn_local}
                domainValue={form.upn_domain}
                onLocal={(v) => setField("upn_local", v)}
                onDomain={(v) => setField("upn_domain", v)}
                domains={domains}
                disabled={!canChangeLogin}
                label={t("users.field.upn")}
                disabledHint={t("users.field.login_admin_only")}
              />
              <Field
                id="sam_account_name"
                label={t("users.field.sam_account_name")}
                value={form.sam_account_name}
                onChange={(v) => setField("sam_account_name", v)}
                maxLength={20}
                disabled={!canChangeLogin}
                hint={
                  canChangeLogin ? t("users.field.sam_hint") : t("users.field.login_admin_only")
                }
              />
            </CardContent>
          </Card>

          {/* Mail */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("users.detail.section_mail")}</CardTitle>
              <CardDescription>{t("users.detail.section_mail_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <UpnField
                localValue={form.mail_local}
                domainValue={form.mail_domain}
                onLocal={(v) => setField("mail_local", v)}
                onDomain={(v) => setField("mail_domain", v)}
                domains={domains}
                disabled={false}
                label={t("users.field.mail")}
                allowEmpty
              />
            </CardContent>
          </Card>

          {/* Adresse */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("users.detail.section_address")}</CardTitle>
              <CardDescription>{t("users.detail.section_address_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                id="street_address"
                label={t("users.field.street_address")}
                value={form.street_address}
                onChange={(v) => setField("street_address", v)}
              />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field
                  id="postal_code"
                  label={t("users.field.postal_code")}
                  value={form.postal_code}
                  onChange={(v) => setField("postal_code", v)}
                  maxLength={16}
                  className="sm:col-span-1"
                />
                <Field
                  id="locality"
                  label={t("users.field.locality")}
                  value={form.locality}
                  onChange={(v) => setField("locality", v)}
                  className="sm:col-span-2"
                />
              </div>
              <Field
                id="country"
                label={t("users.field.country")}
                value={form.country}
                onChange={(v) => setField("country", v)}
              />
            </CardContent>
          </Card>

          {/* Gerät */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("users.detail.section_device")}</CardTitle>
              <CardDescription>{t("users.detail.section_device_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                id="device_name"
                label={t("users.field.device_name")}
                value={user.device_name ?? ""}
                onChange={() => {}}
                readOnly
                hint={t("users.field.device_name_hint")}
              />
              <Field
                id="temp_device_name"
                label={t("users.field.temp_device_name")}
                value={form.temp_device_name}
                onChange={(v) => setField("temp_device_name", v)}
                hint={t("users.field.temp_device_name_hint")}
              />
            </CardContent>
          </Card>

          {/* AD-Konto-Richtlinien */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("users.detail.section_pwpolicy")}</CardTitle>
              <CardDescription>{t("users.detail.section_pwpolicy_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={form.cannot_change_password}
                  onChange={(e) => setField("cannot_change_password", e.target.checked)}
                />
                <span>
                  {t("users.field.cannot_change_password")}
                  <span className="block text-xs text-muted-foreground">
                    {t("users.field.cannot_change_password_hint")}
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={form.password_never_expires}
                  onChange={(e) => setField("password_never_expires", e.target.checked)}
                />
                <span>
                  {t("users.field.password_never_expires")}
                  <span className="block text-xs text-muted-foreground">
                    {t("users.field.password_never_expires_hint")}
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={form.store_password}
                  onChange={(e) => setField("store_password", e.target.checked)}
                />
                <span>
                  {t("users.field.store_password")}
                  <span className="block text-xs text-muted-foreground">
                    {t("users.field.store_password_hint")}
                  </span>
                </span>
              </label>
            </CardContent>
          </Card>

          {user.kind === "student" ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("users.detail.section_grade")}</CardTitle>
                <CardDescription>{t("users.detail.section_grade_desc")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Field
                  id="jahrgangsstufe"
                  label={t("users.field.jahrgangsstufe")}
                  value={form.jahrgangsstufe}
                  onChange={(v) => setField("jahrgangsstufe", v)}
                  hint={t("users.field.jahrgangsstufe_hint")}
                />
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("privacy.section_title")}</CardTitle>
              <CardDescription>{t("privacy.section_desc")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button type="button" variant="outline" onClick={() => setPrivacyOpen(true)}>
                {t("privacy.open_button")}
              </Button>
            </CardContent>
          </Card>

          <div className="flex items-center justify-end gap-3">
            <Button type="button" variant="outline" onClick={cancelEditing}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? t("common.loading") : t("users.detail.save")}
            </Button>
          </div>
        </form>
      )}

      <SubjectAccessModal guid={privacyOpen ? guid : null} onClose={() => setPrivacyOpen(false)} />
      <UserStatusModal user={statusOpen ? user : null} onClose={() => setStatusOpen(false)} />

      <Dialog open={pdfOpen} onOpenChange={(o) => !pdfBusy && setPdfOpen(o)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("users.detail.credential_pdf")}</DialogTitle>
            <DialogDescription>
              {user.cannot_change_password
                ? t("users.detail.credential_pdf_reset_hint")
                : t("users.detail.credential_pdf_masked_hint")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="pdf_heading">{t("users.detail.credential_pdf_heading")}</Label>
              <Input
                id="pdf_heading"
                value={pdfHeading}
                maxLength={200}
                onChange={(e) => setPdfHeading(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="pdf_body">{t("users.detail.credential_pdf_body")}</Label>
              <textarea
                id="pdf_body"
                className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={pdfBody}
                maxLength={4000}
                onChange={(e) => setPdfBody(e.target.value)}
              />
            </div>
            {pdfError ? <p className="text-sm text-destructive">{t("errors.generic")}</p> : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPdfOpen(false)}
              disabled={pdfBusy}
            >
              {t("common.cancel")}
            </Button>
            <Button type="button" onClick={() => void handleDownloadPdf()} disabled={pdfBusy}>
              {pdfBusy ? t("common.loading") : t("users.detail.credential_pdf_download")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// --- Subcomponents --------------------------------------------------------

function UserReadView({
  user,
  dashboard,
  onOpenPrivacy,
}: {
  user: AdUserOut;
  dashboard: UserDashboardOut | undefined;
  onOpenPrivacy: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const address = [
    user.street_address,
    [user.postal_code, user.locality].filter(Boolean).join(" "),
    user.country,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("users.detail.section_classes")}</CardTitle>
        </CardHeader>
        <CardContent>
          {dashboard && dashboard.classes.length > 0 ? (
            <ul className="space-y-3">
              {dashboard.classes.map((c) => (
                <li key={c.class_id} className="text-sm">
                  <span className="font-medium">
                    {c.name}
                    {c.kuerzel ? ` (${c.kuerzel})` : ""}
                  </span>
                  {" · "}
                  {t("classes.jahrgangsstufe")}{" "}
                  {gradeRangeLabel(c.jahrgangsstufe, c.jahrgangsstufe_bis)}
                  {c.teachers.length > 0 ? (
                    <div className="text-muted-foreground">
                      {t("users.detail.class_teachers")}:{" "}
                      {c.teachers
                        .map(
                          (tch) =>
                            `${tch.display_name ?? tch.upn ?? tch.ad_object_guid} (${t(
                              `classes.role_${tch.role}`,
                            )})`,
                        )
                        .join(", ")}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">{t("users.detail.no_classes")}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("users.detail.section_overview")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <InfoRow label={t("users.field.display_name")} value={user.display_name} />
          <InfoRow label={t("users.field.upn")} value={user.upn} />
          <InfoRow label={t("users.field.mail")} value={user.mail} />
          <InfoRow label={t("users.detail.section_address")} value={address || null} />
          <InfoRow label={t("users.field.device_name")} value={user.device_name} />
          <InfoRow label={t("users.field.temp_device_name")} value={user.temp_device_name} />
          {user.kind === "student" ? (
            <InfoRow
              label={t("users.field.jahrgangsstufe")}
              value={user.jahrgangsstufe != null ? gradeLabel(user.jahrgangsstufe) : null}
            />
          ) : null}
          <InfoRow
            label={t("users.field.cannot_change_password")}
            value={user.cannot_change_password ? t("users.yes") : t("users.no")}
          />
          <InfoRow
            label={t("users.field.password_never_expires")}
            value={user.password_never_expires ? t("users.yes") : t("users.no")}
          />
          <div className="flex gap-2 text-sm">
            <span className="w-40 shrink-0 text-muted-foreground">
              {t("users.field.ad_groups")}
            </span>
            <span className="font-medium">
              {user.ad_groups.length > 0 ? user.ad_groups.map((dn) => groupCn(dn)).join(", ") : "–"}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("privacy.section_title")}</CardTitle>
          <CardDescription>{t("privacy.section_desc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" variant="outline" onClick={onOpenPrivacy}>
            {t("privacy.open_button")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/** "CN=Lehrer,OU=Groups,DC=x" → "Lehrer" (falls back to the raw DN). */
function groupCn(dn: string): string {
  const first = dn.split(",")[0] ?? dn;
  return first.replace(/^CN=/i, "") || dn;
}

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}): JSX.Element {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className="font-medium">{value || "–"}</span>
    </div>
  );
}

function BackToList(): JSX.Element {
  const { t } = useTranslation();
  return (
    <Link to="/users" className="text-sm text-muted-foreground hover:underline">
      ← {t("users.title")}
    </Link>
  );
}

interface FieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  maxLength?: number;
  disabled?: boolean;
  readOnly?: boolean;
  className?: string;
}

function Field(props: FieldProps): JSX.Element {
  return (
    <div className={"space-y-1 " + (props.className ?? "")}>
      <Label htmlFor={props.id}>{props.label}</Label>
      <Input
        id={props.id}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        maxLength={props.maxLength}
        disabled={props.disabled}
        readOnly={props.readOnly}
      />
      {props.hint ? <p className="text-xs text-muted-foreground">{props.hint}</p> : null}
    </div>
  );
}

interface UpnFieldProps {
  label: string;
  localValue: string;
  domainValue: string;
  onLocal: (v: string) => void;
  onDomain: (v: string) => void;
  domains: string[];
  disabled?: boolean;
  disabledHint?: string;
  allowEmpty?: boolean;
}

function UpnField(props: UpnFieldProps): JSX.Element {
  const { t } = useTranslation();
  const id = `field-${props.label.replace(/\s+/g, "")}`;
  const idDomain = `${id}-domain`;
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{props.label}</Label>
      <div className="flex flex-wrap items-stretch gap-2">
        <Input
          id={id}
          value={props.localValue}
          onChange={(e) => props.onLocal(e.target.value)}
          disabled={props.disabled}
          className="min-w-[10rem] flex-1"
          placeholder={t("users.field.local_part_placeholder")}
        />
        <span className="flex items-center text-sm text-muted-foreground">@</span>
        <select
          id={idDomain}
          value={props.domainValue}
          onChange={(e) => props.onDomain(e.target.value)}
          disabled={props.disabled || props.domains.length === 0}
          className="h-10 min-w-[12rem] rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
        >
          {props.allowEmpty ? <option value="">{t("users.field.domain_empty")}</option> : null}
          {props.domains.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
          {/* Preserve a legacy domain that's not in the allowlist so we don't
              silently lose data on render. */}
          {props.domainValue && !props.domains.includes(props.domainValue) ? (
            <option value={props.domainValue}>{props.domainValue}</option>
          ) : null}
        </select>
      </div>
      {props.disabled && props.disabledHint ? (
        <p className="text-xs text-muted-foreground">{props.disabledHint}</p>
      ) : props.domains.length === 0 ? (
        <p className="text-xs text-amber-700">{t("users.field.domains_missing")}</p>
      ) : null}
    </div>
  );
}

function UserDetailSkeleton(): JSX.Element {
  return (
    <div className="space-y-6">
      <Skeleton className="h-4 w-32" />
      <Card>
        <CardHeader className="flex flex-row items-center gap-4 space-y-0">
          <Skeleton className="h-14 w-14 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-3 w-72" />
          </div>
        </CardHeader>
      </Card>
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function renderPatchError(err: ApiError, t: (k: string) => string): string {
  if (err.status === 403 && err.code.startsWith("admin_only_field:"))
    return t("users.detail.error_admin_only");
  if (err.status === 404) return t("users.detail.error_not_found");
  if (err.status === 409 && err.code.startsWith("upn_conflict"))
    return t("users.detail.error_upn_conflict");
  if (err.status === 409 && err.code === "user_not_in_ad")
    return t("users.detail.error_user_not_in_ad");
  if (err.status === 422 && err.code.startsWith("mail_domains_not_configured"))
    return t("users.detail.error_mail_domains_missing");
  if (err.status === 422 && err.code.startsWith("domain_not_allowed"))
    return t("users.detail.error_domain_not_allowed");
  if (err.status === 422) return t("users.detail.error_validation");
  if (err.status === 503) return t("errors.ad_unavailable");
  return t("errors.generic");
}
