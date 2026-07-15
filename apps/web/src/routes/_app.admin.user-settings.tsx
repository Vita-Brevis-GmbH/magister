import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAdGroups, useUpdateUserSettings, useUserSettings } from "@/api/hooks";
import type { AdGroupOut, AdUserSettingsOut, AdUserSettingsUpdate } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/user-settings")({
  component: UserSettingsPage,
});

type GroupKey =
  | "ad_groups_teacher"
  | "ad_groups_student_zyklus1"
  | "ad_groups_student_zyklus2"
  | "ad_groups_student_zyklus3";

const GROUP_KEYS: GroupKey[] = [
  "ad_groups_teacher",
  "ad_groups_student_zyklus1",
  "ad_groups_student_zyklus2",
  "ad_groups_student_zyklus3",
];

interface FormState {
  ad_ou_students_zyklus3: string;
  ad_ou_students_other: string;
  ad_ou_teachers: string;
  zyklus1_max_grade: string;
  zyklus2_max_grade: string;
  password_store_enabled: boolean;
  ad_groups_search_base: string;
  ad_groups_teacher: string[];
  ad_groups_student_zyklus1: string[];
  ad_groups_student_zyklus2: string[];
  ad_groups_student_zyklus3: string[];
}

function fromOut(data: AdUserSettingsOut): FormState {
  return {
    ad_ou_students_zyklus3: data.ad_ou_students_zyklus3 ?? "",
    ad_ou_students_other: data.ad_ou_students_other ?? "",
    ad_ou_teachers: data.ad_ou_teachers ?? "",
    zyklus1_max_grade: String(data.zyklus1_max_grade),
    zyklus2_max_grade: String(data.zyklus2_max_grade),
    password_store_enabled: data.password_store_enabled,
    ad_groups_search_base: data.ad_groups_search_base ?? "",
    ad_groups_teacher: [...data.ad_groups_teacher],
    ad_groups_student_zyklus1: [...data.ad_groups_student_zyklus1],
    ad_groups_student_zyklus2: [...data.ad_groups_student_zyklus2],
    ad_groups_student_zyklus3: [...data.ad_groups_student_zyklus3],
  };
}

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function buildPayload(form: FormState, current: AdUserSettingsOut): AdUserSettingsUpdate {
  const payload: AdUserSettingsUpdate = {};
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
  if (Number.isFinite(z1) && z1 !== current.zyklus1_max_grade) payload.zyklus1_max_grade = z1;
  const z2 = Number(form.zyklus2_max_grade);
  if (Number.isFinite(z2) && z2 !== current.zyklus2_max_grade) payload.zyklus2_max_grade = z2;
  if (form.password_store_enabled !== current.password_store_enabled) {
    payload.password_store_enabled = form.password_store_enabled;
  }
  if (form.ad_groups_search_base !== (current.ad_groups_search_base ?? "")) {
    payload.ad_groups_search_base = form.ad_groups_search_base;
  }
  for (const key of GROUP_KEYS) {
    if (!sameList(form[key], current[key])) payload[key] = form[key];
  }
  return payload;
}

function UserSettingsPage(): JSX.Element {
  const { t } = useTranslation();
  const settings = useUserSettings();
  const groups = useAdGroups();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.user_settings.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.user_settings.description")}</p>
      </header>

      {settings.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : settings.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : settings.data ? (
        <UserSettingsForm data={settings.data} groups={groups.data ?? []} />
      ) : null}
    </div>
  );
}

function UserSettingsForm({
  data,
  groups,
}: {
  data: AdUserSettingsOut;
  groups: AdGroupOut[];
}): JSX.Element {
  const { t } = useTranslation();
  const update = useUpdateUserSettings();
  const [form, setForm] = useState<FormState>(() => fromOut(data));
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    setForm(fromOut(data));
  }, [data]);

  function field<K extends keyof FormState>(key: K) {
    return {
      value: form[key] as string,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
        setForm((prev) => ({ ...prev, [key]: e.target.value }));
        setSuccess(false);
      },
    };
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    setSuccess(false);
    update.mutate(buildPayload(form, data), { onSuccess: () => setSuccess(true) });
  }

  const GROUP_LABELS: Record<GroupKey, string> = {
    ad_groups_teacher: "admin.user_settings.field.ad_groups_teacher",
    ad_groups_student_zyklus1: "admin.user_settings.field.ad_groups_student_zyklus1",
    ad_groups_student_zyklus2: "admin.user_settings.field.ad_groups_student_zyklus2",
    ad_groups_student_zyklus3: "admin.user_settings.field.ad_groups_student_zyklus3",
  };

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
          <CardTitle className="text-base">{t("admin.user_settings.ou_section")}</CardTitle>
          <CardDescription>{t("admin.user_settings.ou_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.user_settings.groups_section")}</CardTitle>
          <CardDescription>{t("admin.user_settings.groups_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="groups-base">
              {t("admin.user_settings.field.ad_groups_search_base")}
            </Label>
            <Input
              id="groups-base"
              placeholder="OU=Groups,DC=schule,DC=local"
              {...field("ad_groups_search_base")}
            />
            <p className="text-xs text-muted-foreground">
              {t("admin.user_settings.groups_base_hint")}
            </p>
          </div>
          {GROUP_KEYS.map((key) => (
            <GroupPicker
              key={key}
              label={t(GROUP_LABELS[key])}
              hint={t("admin.user_settings.group_pick_hint")}
              catalog={groups}
              selected={form[key]}
              onChange={(next) => {
                setForm((prev) => ({ ...prev, [key]: next }));
                setSuccess(false);
              }}
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.settings.password_store_title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-input"
              checked={form.password_store_enabled}
              onChange={(e) => {
                setForm((prev) => ({ ...prev, password_store_enabled: e.target.checked }));
                setSuccess(false);
              }}
            />
            <span>
              {t("admin.settings.password_store_enabled")}
              <span className="block text-xs text-muted-foreground">
                {t("admin.settings.password_store_hint")}
              </span>
            </span>
          </label>
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-3">
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? t("common.loading") : t("admin.settings.save")}
        </Button>
      </div>
    </form>
  );
}

export { UserSettingsPage, UserSettingsForm };
