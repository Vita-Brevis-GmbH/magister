import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useCurrentUser, useMyPreferences, useUpdateMyPreferences } from "@/api/hooks";
import type { PrefDateFormat, PrefLanguage, PrefTimeFormat } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import i18n from "@/i18n";

export const Route = createFileRoute("/_app/me")({
  component: MePage,
});

const LANGUAGE_LABELS: Record<PrefLanguage, string> = {
  de: "Deutsch",
  fr: "Français",
  it: "Italiano",
  en: "English",
};
const REGIONS = ["CH", "DE", "FR", "IT", "AT"] as const;
const DATE_FORMATS: PrefDateFormat[] = ["DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"];
const TIME_FORMATS: PrefTimeFormat[] = ["24h", "12h"];

function MePage(): JSX.Element {
  const { t } = useTranslation();
  const me = useCurrentUser();
  if (me.isLoading || !me.data) return <p>{t("common.loading")}</p>;
  const u = me.data;
  return (
    <div className="max-w-xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif">{t("me.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Row label={t("auth.logged_in_as")} value={u.upn} />
          <Row
            label={t("auth.roles")}
            value={u.roles.length ? u.roles.join(", ") : t("auth.no_roles")}
          />
          <Row
            label={t("auth.school_scope")}
            value={u.school_scope.length ? u.school_scope.join(", ") : "–"}
          />
          <Row label={t("auth.expires_at")} value={u.expires_at} mono />
        </CardContent>
      </Card>

      <PreferencesCard />
    </div>
  );
}

function PreferencesCard(): JSX.Element {
  const { t } = useTranslation();
  const prefs = useMyPreferences();
  const update = useUpdateMyPreferences();

  const [language, setLanguage] = useState<PrefLanguage>("de");
  const [region, setRegion] = useState("CH");
  const [dateFormat, setDateFormat] = useState<PrefDateFormat>("DD.MM.YYYY");
  const [timeFormat, setTimeFormat] = useState<PrefTimeFormat>("24h");

  useEffect(() => {
    if (!prefs.data) return;
    setLanguage(prefs.data.language);
    setRegion(prefs.data.region);
    setDateFormat(prefs.data.date_format);
    setTimeFormat(prefs.data.time_format);
  }, [prefs.data]);

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    update.mutate(
      { language, region, date_format: dateFormat, time_format: timeFormat },
      { onSuccess: () => void i18n.changeLanguage(language) },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("me.preferences_title")}</CardTitle>
        <CardDescription>{t("me.preferences_desc")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {update.isError ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t("errors.generic")}
            </div>
          ) : update.isSuccess ? (
            <div
              role="status"
              className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
            >
              {t("me.preferences_saved")}
            </div>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="pref-language">{t("me.pref_language")}</Label>
            <select
              id="pref-language"
              value={language}
              onChange={(e) => setLanguage(e.target.value as PrefLanguage)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {(Object.keys(LANGUAGE_LABELS) as PrefLanguage[]).map((l) => (
                <option key={l} value={l}>
                  {LANGUAGE_LABELS[l]}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="pref-region">{t("me.pref_region")}</Label>
            <select
              id="pref-region"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="pref-date">{t("me.pref_date_format")}</Label>
              <select
                id="pref-date"
                value={dateFormat}
                onChange={(e) => setDateFormat(e.target.value as PrefDateFormat)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {DATE_FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="pref-time">{t("me.pref_time_format")}</Label>
              <select
                id="pref-time"
                value={timeFormat}
                onChange={(e) => setTimeFormat(e.target.value as PrefTimeFormat)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {TIME_FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <Button type="submit" disabled={update.isPending || prefs.isLoading}>
            {update.isPending ? t("common.loading") : t("me.preferences_save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}): JSX.Element {
  return (
    <div className="flex flex-wrap gap-x-4">
      <span className="text-muted-foreground">{label}:</span>
      <span className={mono ? "font-mono" : undefined}>{value}</span>
    </div>
  );
}
