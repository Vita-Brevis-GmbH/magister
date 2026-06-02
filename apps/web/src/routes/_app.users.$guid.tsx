import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useCurrentUser, useMailDomains, useUpdateUser, useUser } from "@/api/hooks";
import type { UserAttributesUpdate } from "@/api/types";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { SubjectAccessModal } from "@/components/SubjectAccessModal";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { displayLabel } from "@/lib/userDisplay";

export const Route = createFileRoute("/_app/users/$guid")({
  component: UserDetailPage,
});

interface FormState {
  display_name: string;
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
}

function emptyForm(): FormState {
  return {
    display_name: "",
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
  };
}

function splitMail(value: string | null | undefined): { local: string; domain: string } {
  if (!value) return { local: "", domain: "" };
  const [local, domain = ""] = value.split("@");
  return { local: local ?? "", domain };
}

function UserDetailPage(): JSX.Element {
  const { t } = useTranslation();
  const { guid } = Route.useParams();
  const userQ = useUser(guid);
  const mailDomainsQ = useMailDomains();
  const me = useCurrentUser();
  const update = useUpdateUser(guid);

  const canChangeLogin = me.data?.is_admin ?? false;
  const domains = mailDomainsQ.data?.domains ?? [];

  const [form, setForm] = useState<FormState>(emptyForm);
  const [savedFlash, setSavedFlash] = useState(false);
  const [privacyOpen, setPrivacyOpen] = useState(false);

  // Re-hydrate the form when the loaded user (or available domains) change.
  useEffect(() => {
    if (!userQ.data) return;
    const upn = splitMail(userQ.data.upn);
    const mail = splitMail(userQ.data.mail);
    setForm({
      display_name: userQ.data.display_name ?? "",
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
    });
  }, [userQ.data]);

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

    const addressFields: Array<keyof FormState & keyof UserAttributesUpdate> = [
      "street_address",
      "locality",
      "postal_code",
      "country",
      "temp_device_name",
    ];
    for (const f of addressFields) {
      const next = trimOrNull(form[f]);
      const cur = (current as unknown as Record<string, string | null>)[f] ?? null;
      if (next !== cur) out[f] = next;
    }

    return out;
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const payload = buildPayload();
    if (Object.keys(payload).length === 0) return;
    update.mutate(payload, {
      onSuccess: () => setSavedFlash(true),
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
        </CardHeader>
      </Card>

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
              hint={canChangeLogin ? t("users.field.sam_hint") : t("users.field.login_admin_only")}
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
          <BackToList />
          <Button type="submit" disabled={update.isPending}>
            {update.isPending ? t("common.loading") : t("users.detail.save")}
          </Button>
        </div>
      </form>

      <SubjectAccessModal guid={privacyOpen ? guid : null} onClose={() => setPrivacyOpen(false)} />
    </div>
  );
}

// --- Subcomponents --------------------------------------------------------

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
