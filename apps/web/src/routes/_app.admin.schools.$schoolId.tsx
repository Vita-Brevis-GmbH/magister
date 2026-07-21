import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAdGroups, useSchool, useUpdateSchool } from "@/api/hooks";
import type { AdGroupOut, SchoolOut, SchoolUpdate } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/schools/$schoolId")({
  component: SchoolAdConfigPage,
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
  ad_ou_devices: string;
  ad_groups_teacher: string[];
  ad_groups_student_zyklus1: string[];
  ad_groups_student_zyklus2: string[];
  ad_groups_student_zyklus3: string[];
}

function fromSchool(s: SchoolOut): FormState {
  return {
    ad_ou_students_zyklus3: s.ad_ou_students_zyklus3 ?? "",
    ad_ou_students_other: s.ad_ou_students_other ?? "",
    ad_ou_teachers: s.ad_ou_teachers ?? "",
    ad_ou_devices: s.ad_ou_devices ?? "",
    ad_groups_teacher: [...s.ad_groups_teacher],
    ad_groups_student_zyklus1: [...s.ad_groups_student_zyklus1],
    ad_groups_student_zyklus2: [...s.ad_groups_student_zyklus2],
    ad_groups_student_zyklus3: [...s.ad_groups_student_zyklus3],
  };
}

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function buildPayload(form: FormState, current: SchoolOut): SchoolUpdate {
  const payload: SchoolUpdate = {};
  if (form.ad_ou_students_zyklus3 !== (current.ad_ou_students_zyklus3 ?? "")) {
    payload.ad_ou_students_zyklus3 = form.ad_ou_students_zyklus3;
  }
  if (form.ad_ou_students_other !== (current.ad_ou_students_other ?? "")) {
    payload.ad_ou_students_other = form.ad_ou_students_other;
  }
  if (form.ad_ou_teachers !== (current.ad_ou_teachers ?? "")) {
    payload.ad_ou_teachers = form.ad_ou_teachers;
  }
  if (form.ad_ou_devices !== (current.ad_ou_devices ?? "")) {
    payload.ad_ou_devices = form.ad_ou_devices;
  }
  for (const key of GROUP_KEYS) {
    if (!sameList(form[key], current[key])) payload[key] = form[key];
  }
  return payload;
}

function SchoolAdConfigPage(): JSX.Element {
  const { t } = useTranslation();
  const { schoolId } = Route.useParams();
  const id = Number(schoolId);
  const q = useSchool(Number.isNaN(id) ? 0 : id);
  const groups = useAdGroups();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <Link to="/admin/schools" className="text-sm text-primary hover:underline">
          ← {t("schools.title")}
        </Link>
        <h1 className="font-serif text-2xl font-semibold">
          {q.data ? q.data.name : t("schools.ad_config.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("schools.ad_config.subtitle")}</p>
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : q.data ? (
        <SchoolAdConfigForm data={q.data} groups={groups.data ?? []} />
      ) : null}
    </div>
  );
}

function SchoolAdConfigForm({
  data,
  groups,
}: {
  data: SchoolOut;
  groups: AdGroupOut[];
}): JSX.Element {
  const { t } = useTranslation();
  const update = useUpdateSchool(data.id);
  const [form, setForm] = useState<FormState>(() => fromSchool(data));
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    setForm(fromSchool(data));
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
    ad_groups_teacher: "schools.ad_config.field.ad_groups_teacher",
    ad_groups_student_zyklus1: "schools.ad_config.field.ad_groups_student_zyklus1",
    ad_groups_student_zyklus2: "schools.ad_config.field.ad_groups_student_zyklus2",
    ad_groups_student_zyklus3: "schools.ad_config.field.ad_groups_student_zyklus3",
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
          <CardTitle className="text-base">{t("schools.ad_config.ou_section")}</CardTitle>
          <CardDescription>{t("schools.ad_config.ou_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="ou-z3">{t("schools.ad_config.field.ad_ou_students_zyklus3")}</Label>
            <Input
              id="ou-z3"
              placeholder="OU=SekI,OU=Schule,DC=…"
              {...field("ad_ou_students_zyklus3")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ou-other">{t("schools.ad_config.field.ad_ou_students_other")}</Label>
            <Input
              id="ou-other"
              placeholder="OU=Schueler,OU=Schule,DC=…"
              {...field("ad_ou_students_other")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ou-teachers">{t("schools.ad_config.field.ad_ou_teachers")}</Label>
            <Input
              id="ou-teachers"
              placeholder="OU=Lehrer,OU=Schule,DC=…"
              {...field("ad_ou_teachers")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ou-devices">{t("schools.ad_config.field.ad_ou_devices")}</Label>
            <Input
              id="ou-devices"
              placeholder="OU=Geraete,OU=Schule,DC=…"
              {...field("ad_ou_devices")}
            />
          </div>
          <p className="text-xs text-muted-foreground">{t("schools.ad_config.ou_hint")}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("schools.ad_config.groups_section")}</CardTitle>
          <CardDescription>{t("schools.ad_config.groups_section_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {GROUP_KEYS.map((key) => (
            <GroupPicker
              key={key}
              label={t(GROUP_LABELS[key])}
              hint={t("schools.ad_config.group_pick_hint")}
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

      <div className="flex items-center justify-end gap-3">
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? t("common.loading") : t("admin.settings.save")}
        </Button>
      </div>
    </form>
  );
}

export { SchoolAdConfigPage, SchoolAdConfigForm };
