import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAppSettings, useTestAdConnection, useUpdateAppSettings } from "@/api/hooks";
import type { AppSettingsOut, AppSettingsUpdate } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/settings")({
  component: AppSettingsPage,
});

interface FormState {
  oidc_issuer: string;
  oidc_client_id: string;
  oidc_client_secret: string;
  oidc_redirect_uri: string;
  oidc_scopes: string;
  bootstrap_admins: string;
  mail_domains: string;
  ad_dcs: string;
  ad_bind_dn: string;
  ad_bind_password: string;
  ad_users_search_base: string;
  ad_computers_search_base: string;
  ad_sync_interval_minutes: string;
  ad_ou_students_zyklus3: string;
  ad_ou_students_other: string;
  ad_ou_teachers: string;
  zyklus1_max_grade: string;
  zyklus2_max_grade: string;
}

function fromOut(data: AppSettingsOut): FormState {
  return {
    oidc_issuer: data.oidc_issuer ?? "",
    oidc_client_id: data.oidc_client_id ?? "",
    oidc_client_secret: "", // never prefilled — placeholder communicates "set"
    oidc_redirect_uri: data.oidc_redirect_uri ?? "",
    oidc_scopes: data.oidc_scopes.join(", "),
    bootstrap_admins: data.bootstrap_admins.join(", "),
    mail_domains: data.mail_domains.join(", "),
    ad_dcs: data.ad_dcs.join(", "),
    ad_bind_dn: data.ad_bind_dn ?? "",
    ad_bind_password: "",
    ad_users_search_base: data.ad_users_search_base ?? "",
    ad_computers_search_base: data.ad_computers_search_base ?? "",
    ad_sync_interval_minutes: String(data.ad_sync_interval_minutes),
    ad_ou_students_zyklus3: data.ad_ou_students_zyklus3 ?? "",
    ad_ou_students_other: data.ad_ou_students_other ?? "",
    ad_ou_teachers: data.ad_ou_teachers ?? "",
    zyklus1_max_grade: String(data.zyklus1_max_grade),
    zyklus2_max_grade: String(data.zyklus2_max_grade),
  };
}

function splitCsv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function buildPayload(form: FormState, current: AppSettingsOut): AppSettingsUpdate {
  const payload: AppSettingsUpdate = {};
  if (form.oidc_issuer !== (current.oidc_issuer ?? "")) {
    payload.oidc_issuer = form.oidc_issuer || null;
  }
  if (form.oidc_client_id !== (current.oidc_client_id ?? "")) {
    payload.oidc_client_id = form.oidc_client_id || null;
  }
  // Only send the secret fields when the operator actually typed something.
  if (form.oidc_client_secret) payload.oidc_client_secret = form.oidc_client_secret;
  if (form.ad_bind_password) payload.ad_bind_password = form.ad_bind_password;
  if (form.oidc_redirect_uri !== (current.oidc_redirect_uri ?? "")) {
    payload.oidc_redirect_uri = form.oidc_redirect_uri || null;
  }
  const scopes = splitCsv(form.oidc_scopes);
  if (JSON.stringify(scopes) !== JSON.stringify(current.oidc_scopes)) {
    payload.oidc_scopes = scopes;
  }
  const admins = splitCsv(form.bootstrap_admins);
  if (JSON.stringify(admins) !== JSON.stringify(current.bootstrap_admins)) {
    payload.bootstrap_admins = admins;
  }
  const mail_domains = splitCsv(form.mail_domains).map((d) => d.toLowerCase());
  if (JSON.stringify(mail_domains) !== JSON.stringify(current.mail_domains)) {
    payload.mail_domains = mail_domains;
  }
  const dcs = splitCsv(form.ad_dcs);
  if (JSON.stringify(dcs) !== JSON.stringify(current.ad_dcs)) {
    payload.ad_dcs = dcs;
  }
  if (form.ad_bind_dn !== (current.ad_bind_dn ?? "")) {
    payload.ad_bind_dn = form.ad_bind_dn || null;
  }
  if (form.ad_users_search_base !== (current.ad_users_search_base ?? "")) {
    payload.ad_users_search_base = form.ad_users_search_base || null;
  }
  if (form.ad_computers_search_base !== (current.ad_computers_search_base ?? "")) {
    payload.ad_computers_search_base = form.ad_computers_search_base || null;
  }
  const interval = Number(form.ad_sync_interval_minutes);
  if (Number.isFinite(interval) && interval !== current.ad_sync_interval_minutes) {
    payload.ad_sync_interval_minutes = interval;
  }
  if (form.ad_ou_students_zyklus3 !== (current.ad_ou_students_zyklus3 ?? "")) {
    payload.ad_ou_students_zyklus3 = form.ad_ou_students_zyklus3;
  }
  if (form.ad_ou_students_other !== (current.ad_ou_students_other ?? "")) {
    payload.ad_ou_students_other = form.ad_ou_students_other;
  }
  if (form.ad_ou_teachers !== (current.ad_ou_teachers ?? "")) {
    payload.ad_ou_teachers = form.ad_ou_teachers;
  }
  const z1 = Number(form.zyklus1_max_grade);
  if (Number.isFinite(z1) && z1 !== current.zyklus1_max_grade) {
    payload.zyklus1_max_grade = z1;
  }
  const z2 = Number(form.zyklus2_max_grade);
  if (Number.isFinite(z2) && z2 !== current.zyklus2_max_grade) {
    payload.zyklus2_max_grade = z2;
  }
  return payload;
}

function AppSettingsPage(): JSX.Element {
  const { t } = useTranslation();
  const settings = useAppSettings();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.settings.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.settings.description")}</p>
      </header>

      {settings.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : settings.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : settings.data ? (
        <SettingsForm data={settings.data} />
      ) : null}
    </div>
  );
}

function SettingsForm({ data }: { data: AppSettingsOut }): JSX.Element {
  const { t } = useTranslation();
  const update = useUpdateAppSettings();
  const testAd = useTestAdConnection();
  const [form, setForm] = useState<FormState>(() => fromOut(data));
  const [success, setSuccess] = useState(false);

  // Re-sync when the upstream changes (e.g. after our own PUT).
  useEffect(() => {
    setForm(fromOut(data));
  }, [data]);

  function field<K extends keyof FormState>(key: K) {
    return {
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
        setForm((prev) => ({ ...prev, [key]: e.target.value }));
        setSuccess(false);
      },
    };
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    setSuccess(false);
    const payload = buildPayload(form, data);
    update.mutate(payload, {
      onSuccess: () => setSuccess(true),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {update.isError ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {update.error instanceof ApiError && update.error.status === 422
            ? t("admin.settings.error_invalid")
            : t("errors.generic")}
        </div>
      ) : null}
      {success ? (
        <div
          role="status"
          className="rounded-md border border-green-500/50 bg-green-500/10 px-3 py-2 text-sm text-green-700 dark:text-green-300"
        >
          {t("admin.settings.success")}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.settings.oidc_section")}</CardTitle>
          <CardDescription>{t("admin.settings.oidc_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="oidc-issuer">{t("admin.settings.field.oidc_issuer")}</Label>
            <Input id="oidc-issuer" {...field("oidc_issuer")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="oidc-client-id">{t("admin.settings.field.oidc_client_id")}</Label>
            <Input id="oidc-client-id" {...field("oidc_client_id")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="oidc-client-secret">
              {t("admin.settings.field.oidc_client_secret")}
            </Label>
            <Input
              id="oidc-client-secret"
              type="password"
              autoComplete="new-password"
              placeholder={
                data.oidc_client_secret_set
                  ? t("admin.settings.placeholder_secret_set")
                  : t("admin.settings.placeholder_secret_unset")
              }
              {...field("oidc_client_secret")}
            />
            <p className="text-xs text-muted-foreground">
              {t("admin.settings.field.oidc_client_secret_hint")}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="oidc-redirect-uri">{t("admin.settings.field.oidc_redirect_uri")}</Label>
            <Input id="oidc-redirect-uri" {...field("oidc_redirect_uri")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="oidc-scopes">{t("admin.settings.field.oidc_scopes")}</Label>
            <Input id="oidc-scopes" {...field("oidc_scopes")} />
            <p className="text-xs text-muted-foreground">{t("admin.settings.csv_hint")}</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="bootstrap-admins">{t("admin.settings.field.bootstrap_admins")}</Label>
            <Input id="bootstrap-admins" {...field("bootstrap_admins")} />
            <p className="text-xs text-muted-foreground">{t("admin.settings.csv_hint")}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.settings.ad_section")}</CardTitle>
          <CardDescription>{t("admin.settings.ad_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="ad-dcs">{t("admin.settings.field.ad_dcs")}</Label>
            <Input id="ad-dcs" {...field("ad_dcs")} />
            <p className="text-xs text-muted-foreground">{t("admin.settings.csv_hint")}</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ad-bind-dn">{t("admin.settings.field.ad_bind_dn")}</Label>
            <Input id="ad-bind-dn" {...field("ad_bind_dn")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ad-bind-password">{t("admin.settings.field.ad_bind_password")}</Label>
            <Input
              id="ad-bind-password"
              type="password"
              autoComplete="new-password"
              placeholder={
                data.ad_bind_password_set
                  ? t("admin.settings.placeholder_secret_set")
                  : t("admin.settings.placeholder_secret_unset")
              }
              {...field("ad_bind_password")}
            />
            <p className="text-xs text-muted-foreground">
              {t("admin.settings.field.ad_bind_password_hint")}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ad-search-base">{t("admin.settings.field.ad_users_search_base")}</Label>
            <Input id="ad-search-base" {...field("ad_users_search_base")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ad-computers-search-base">
              {t("admin.settings.field.ad_computers_search_base")}
            </Label>
            <Input id="ad-computers-search-base" {...field("ad_computers_search_base")} />
            <p className="text-xs text-muted-foreground">
              {t("admin.settings.field.ad_computers_search_base_hint")}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ad-sync-interval">
              {t("admin.settings.field.ad_sync_interval_minutes")}
            </Label>
            <Input
              id="ad-sync-interval"
              type="number"
              min={1}
              max={1440}
              {...field("ad_sync_interval_minutes")}
            />
          </div>

          <div className="space-y-3 border-t pt-4">
            <p className="text-sm font-medium">{t("admin.settings.provisioning_title")}</p>
            <p className="text-xs text-muted-foreground">{t("admin.settings.provisioning_hint")}</p>
            <div className="space-y-1">
              <Label htmlFor="ou-z3">{t("admin.settings.field.ad_ou_students_zyklus3")}</Label>
              <Input
                id="ou-z3"
                placeholder="OU=SekI,OU=Schule,DC=…"
                {...field("ad_ou_students_zyklus3")}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ou-other">{t("admin.settings.field.ad_ou_students_other")}</Label>
              <Input
                id="ou-other"
                placeholder="OU=Schueler,OU=Schule,DC=…"
                {...field("ad_ou_students_other")}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ou-teachers">{t("admin.settings.field.ad_ou_teachers")}</Label>
              <Input
                id="ou-teachers"
                placeholder="OU=Lehrer,OU=Schule,DC=…"
                {...field("ad_ou_teachers")}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="z1max">{t("admin.settings.field.zyklus1_max_grade")}</Label>
                <Input id="z1max" type="number" min={1} max={13} {...field("zyklus1_max_grade")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="z2max">{t("admin.settings.field.zyklus2_max_grade")}</Label>
                <Input id="z2max" type="number" min={1} max={13} {...field("zyklus2_max_grade")} />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">{t("admin.settings.zyklus_hint")}</p>
          </div>

          <div className="space-y-2 border-t pt-4">
            <div className="flex items-center gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => testAd.mutate()}
                disabled={testAd.isPending}
              >
                {testAd.isPending ? t("common.loading") : t("admin.settings.test_ad_button")}
              </Button>
              {testAd.data ? (
                <span
                  className={
                    testAd.data.ok ? "text-sm text-emerald-700" : "text-sm text-destructive"
                  }
                >
                  {testAd.data.ok
                    ? t("admin.settings.test_ad_ok")
                    : t("admin.settings.test_ad_failed")}
                </span>
              ) : testAd.isError ? (
                <span className="text-sm text-destructive">{t("errors.generic")}</span>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">{t("admin.settings.test_ad_hint")}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.settings.mail_section")}</CardTitle>
          <CardDescription>{t("admin.settings.mail_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="mail-domains">{t("admin.settings.field.mail_domains")}</Label>
            <Input id="mail-domains" {...field("mail_domains")} />
            <p className="text-xs text-muted-foreground">{t("admin.settings.csv_hint")}</p>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-3">
        <span className="text-xs text-muted-foreground">
          {t("admin.settings.last_updated")}: {data.updated_at}
          {data.updated_by_upn ? ` · ${data.updated_by_upn}` : ""}
        </span>
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? t("common.loading") : t("admin.settings.save")}
        </Button>
      </div>
    </form>
  );
}

// Make sure the named exports stay stable for the test suite.
export { AppSettingsPage, SettingsForm };
