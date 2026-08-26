import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, apiFetch } from "@/api/client";
import {
  useClasses,
  useCreateAdUser,
  useInstanceProfile,
  useMailDomains,
  useSchools,
} from "@/api/hooks";
import type { AdUserOuKey } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/user-new")({
  component: NewUserPage,
});

const SCHOOL_OU_KEYS: AdUserOuKey[] = [
  "teacher",
  "student_zyklus1",
  "student_zyklus2",
  "student_zyklus3",
];

const selectClasses =
  "flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

const INITIAL = {
  given_name: "",
  surname: "",
  display_name: "",
  sam_account_name: "",
  user_principal_name: "",
  upn_local: "",
  upn_domain: "",
  mail: "",
  school_id: "",
  ou_key: "teacher" as AdUserOuKey,
  jahrgangsstufe: "",
  class_id: "",
  force_change: true,
  cannot_change_password: false,
  password_never_expires: false,
};

function createErrorKey(err: ApiError): string {
  if (err.status === 409) return "admin.user_new.err_ou_not_configured";
  if (err.status === 503) return "admin.user_new.err_ad";
  if (err.status === 422) return "admin.user_new.err_invalid";
  return "errors.generic";
}

function NewUserPage(): JSX.Element {
  const { t } = useTranslation();
  const { tt } = useTerms();
  const navigate = useNavigate();
  const create = useCreateAdUser();
  const classes = useClasses();
  const schools = useSchools();
  const isCompany = (useInstanceProfile().data ?? "school") === "company";
  // Configured UPN/mail domains (app_settings.mail_domains): when present, the
  // UPN is composed as localpart + a domain picked from a dropdown; otherwise
  // the admin types the full UPN (fallback for instances with no domains set).
  const mailDomainsQ = useMailDomains();
  const domains = mailDomainsQ.data?.domains ?? [];
  const useDomainPicker = domains.length > 0;

  const [form, setForm] = useState(INITIAL);
  const [password, setPassword] = useState<string | null>(null);
  const [classWarn, setClassWarn] = useState(false);

  // Company provisions a single "company" category into the org unit's company
  // OU; school offers teacher + student Zyklen. Students carry a grade + class.
  const ouKeys = isCompany ? (["company"] as AdUserOuKey[]) : SCHOOL_OU_KEYS;
  const ouKey: AdUserOuKey = isCompany ? "company" : form.ou_key;
  const isStudent = !isCompany && form.ou_key !== "teacher";

  const schoolList = schools.data ?? [];
  // Pre-select the target org unit when there is exactly one to choose from.
  useEffect(() => {
    const list = schools.data ?? [];
    if (list.length === 1) {
      setForm((prev) =>
        prev.school_id === "" ? { ...prev, school_id: String(list[0].id) } : prev,
      );
    }
  }, [schools.data]);
  // Default the UPN domain to the first configured one.
  useEffect(() => {
    const list = mailDomainsQ.data?.domains ?? [];
    if (list.length > 0) {
      setForm((prev) => (prev.upn_domain === "" ? { ...prev, upn_domain: list[0] } : prev));
    }
  }, [mailDomainsQ.data]);

  // The effective UPN: composed from localpart + picked domain, or the raw
  // free-text field when no domains are configured.
  const composedUpn = useDomainPicker
    ? `${form.upn_local.trim()}@${form.upn_domain}`
    : form.user_principal_name.trim();

  function field(key: keyof typeof form) {
    return {
      value: form[key] as string,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        setForm((prev) => ({ ...prev, [key]: e.target.value })),
    };
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!form.school_id) return;
    if (useDomainPicker && !form.upn_local.trim()) return;
    setPassword(null);
    setClassWarn(false);
    const grade = form.jahrgangsstufe.trim();
    create.mutate(
      {
        given_name: form.given_name,
        surname: form.surname,
        display_name: form.display_name.trim() || null,
        sam_account_name: form.sam_account_name,
        user_principal_name: composedUpn,
        mail: form.mail || null,
        ou_key: ouKey,
        school_id: Number(form.school_id),
        force_change: form.force_change,
        cannot_change_password: form.cannot_change_password,
        password_never_expires: form.password_never_expires,
        jahrgangsstufe: isStudent && grade !== "" ? Number(grade) : null,
      },
      {
        onSuccess: async (res) => {
          // Optional class membership (students only) — reuse the class-roster
          // endpoint. A membership failure must not hide the created password.
          if (isStudent && form.class_id) {
            try {
              await apiFetch(`/classes/${form.class_id}/students`, {
                method: "POST",
                body: { ad_object_guid: res.ad_object_guid },
              });
            } catch {
              setClassWarn(true);
            }
          }
          setPassword(res.temp_password);
        },
      },
    );
  }

  if (password) {
    return (
      <div className="mx-auto max-w-lg space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("admin.user_new.created_title")}</CardTitle>
            <CardDescription>{t("admin.user_new.created_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>{t("admin.user_new.temp_password")}</Label>
              <div className="rounded-md border bg-muted px-3 py-2 font-mono text-sm">
                {password}
              </div>
              <p className="text-xs text-muted-foreground">{t("admin.user_new.temp_hint")}</p>
            </div>
            {classWarn ? (
              <p className="text-sm text-amber-600">{t("admin.user_new.class_assign_failed")}</p>
            ) : null}
            <div className="flex gap-2">
              <Button type="button" onClick={() => navigate({ to: "/users" })}>
                {t("admin.user_new.to_users")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setPassword(null);
                  setClassWarn(false);
                  setForm(INITIAL);
                }}
              >
                {t("admin.user_new.create_another")}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const activeClasses = (classes.data ?? []).filter((c) => c.status === "active");

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.user_new.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.user_new.description")}</p>
      </header>
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {create.isError ? (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t(createErrorKey(create.error))}
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="given">{t("admin.user_new.given_name")}</Label>
                <Input id="given" required {...field("given_name")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="surname">{t("admin.user_new.surname")}</Label>
                <Input id="surname" required {...field("surname")} />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="display">{t("admin.user_new.display_name")}</Label>
              <Input id="display" autoComplete="off" {...field("display_name")} />
              <p className="text-xs text-muted-foreground">
                {t("admin.user_new.display_name_hint")}
              </p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sam">{t("admin.user_new.sam")}</Label>
              <Input id="sam" required autoComplete="off" {...field("sam_account_name")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="upn">{t("admin.user_new.upn")}</Label>
              {useDomainPicker ? (
                <div className="flex items-center gap-2">
                  <Input
                    id="upn"
                    required
                    autoComplete="off"
                    placeholder="vorname.nachname"
                    className="flex-1"
                    {...field("upn_local")}
                  />
                  <span className="text-sm text-muted-foreground">@</span>
                  <select
                    aria-label={t("admin.user_new.upn_domain")}
                    className={`${selectClasses} w-auto`}
                    value={form.upn_domain}
                    onChange={(e) => setForm((prev) => ({ ...prev, upn_domain: e.target.value }))}
                  >
                    {domains.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <Input
                  id="upn"
                  required
                  autoComplete="off"
                  placeholder="vorname.nachname@schule.ch"
                  {...field("user_principal_name")}
                />
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="mail">{t("admin.user_new.mail")}</Label>
              <Input id="mail" type="email" autoComplete="off" {...field("mail")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="unit">{tt("admin.user_new.unit")}</Label>
              <select
                id="unit"
                className={selectClasses}
                value={form.school_id}
                onChange={(e) => setForm((prev) => ({ ...prev, school_id: e.target.value }))}
              >
                <option value="">{tt("admin.user_new.unit_placeholder")}</option>
                {schoolList.map((s) => (
                  <option key={s.id} value={String(s.id)}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="ou">{t("admin.user_new.ou")}</Label>
              <select
                id="ou"
                className={selectClasses}
                value={ouKey}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, ou_key: e.target.value as AdUserOuKey }))
                }
              >
                {ouKeys.map((k) => (
                  <option key={k} value={k}>
                    {tt(`admin.user_new.ou_${k}`)}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{t("admin.user_new.ou_hint")}</p>
            </div>

            {isStudent ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="grade">{t("admin.user_new.jahrgangsstufe")}</Label>
                  <Input id="grade" type="number" min={-1} max={13} {...field("jahrgangsstufe")} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="class">{t("admin.user_new.class")}</Label>
                  <select
                    id="class"
                    className={selectClasses}
                    value={form.class_id}
                    onChange={(e) => setForm((prev) => ({ ...prev, class_id: e.target.value }))}
                  >
                    <option value="">{t("admin.user_new.class_none")}</option>
                    {activeClasses.map((c) => (
                      <option key={c.id} value={String(c.id)}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ) : null}

            <div className="space-y-2 border-t pt-3">
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={form.force_change}
                  onChange={(e) => setForm((prev) => ({ ...prev, force_change: e.target.checked }))}
                />
                <span>{t("admin.user_new.force_change")}</span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={!form.cannot_change_password}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, cannot_change_password: !e.target.checked }))
                  }
                />
                <span>{t("admin.user_new.can_change_password")}</span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={form.password_never_expires}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, password_never_expires: e.target.checked }))
                  }
                />
                <span>{t("admin.user_new.password_never_expires")}</span>
              </label>
            </div>

            <Button
              type="submit"
              disabled={
                create.isPending || !form.school_id || (useDomainPicker && !form.upn_local.trim())
              }
            >
              {create.isPending ? t("common.loading") : t("admin.user_new.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
