import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  useAdGroups,
  useArchiveDepartment,
  useCreateDepartment,
  useCurrentUser,
  useDepartments,
  useSchools,
  useUpdateDepartment,
} from "@/api/hooks";
import type { DepartmentOut } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/departments")({
  component: DepartmentsPage,
});

function DepartmentsPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const q = useDepartments();
  const schools = useSchools();
  const create = useCreateDepartment();
  const me = useCurrentUser();
  const isAdmin = me.data?.is_admin ?? false;
  const [name, setName] = useState("");
  const [kuerzel, setKuerzel] = useState("");
  // "" = not chosen, "global" = standortübergreifend (admin only), number = Standort.
  const [schoolId, setSchoolId] = useState<number | "" | "global">("");

  const schoolList = useMemo(() => schools.data ?? [], [schools.data]);
  // Pre-select the org unit when there is exactly one to choose from.
  useEffect(() => {
    if (schoolId === "" && schoolList.length === 1) setSchoolId(schoolList[0].id);
  }, [schoolList, schoolId]);

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (!name.trim() || schoolId === "") return;
    create.mutate(
      {
        name: name.trim(),
        kuerzel: kuerzel.trim() || null,
        school_id: schoolId === "global" ? null : schoolId,
      },
      {
        onSuccess: () => {
          setName("");
          setKuerzel("");
        },
      },
    );
  };

  const noUnits = !schools.isLoading && schoolList.length === 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          {t("departments.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("departments.intro")}</p>
      </header>

      {noUnits ? (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm">
          {t("departments.no_units", { unit: terms.unit })}{" "}
          <Link to="/admin/schools" className="font-medium underline">
            {t("departments.no_units_link", { unit: terms.unit })}
          </Link>
        </div>
      ) : (
        <form
          onSubmit={submit}
          className="flex flex-wrap items-end gap-3 rounded-md border bg-card px-4 py-3"
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">{terms.unit}</span>
            <select
              value={schoolId}
              onChange={(e) => {
                const v = e.target.value;
                setSchoolId(v === "" ? "" : v === "global" ? "global" : Number(v));
              }}
              className="h-9 w-56 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">{t("departments.select_unit", { unit: terms.unit })}</option>
              {isAdmin ? (
                <option value="global">
                  {t("departments.global_option", { unit: terms.unit })}
                </option>
              ) : null}
              {schoolList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.name")}
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("departments.name_placeholder")}
              className="h-9 w-56 rounded-md border border-input bg-background px-3 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.kuerzel")}
            </span>
            <input
              value={kuerzel}
              onChange={(e) => setKuerzel(e.target.value)}
              className="h-9 w-32 rounded-md border border-input bg-background px-3 text-sm"
            />
          </label>
          <Button
            type="submit"
            size="sm"
            disabled={create.isPending || !name.trim() || schoolId === ""}
          >
            {t("departments.create")}
          </Button>
        </form>
      )}

      {create.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("departments.create_failed")}
        </p>
      ) : null}

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : q.isLoading || !q.data ? (
        <p className="text-sm text-muted-foreground">{t("departments.loading")}</p>
      ) : q.data.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center">
          <p className="text-sm text-muted-foreground">{t("departments.empty")}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <ul className="divide-y">
            {q.data.map((d) => (
              <DepartmentRow key={d.id} dept={d} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DepartmentRow({ dept }: { dept: DepartmentOut }): JSX.Element {
  const { t } = useTranslation();
  const archive = useArchiveDepartment();
  const update = useUpdateDepartment();
  const groups = useAdGroups();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(dept.name);
  const [kuerzel, setKuerzel] = useState(dept.kuerzel ?? "");
  const [adGroups, setAdGroups] = useState<string[]>(dept.ad_groups);

  const startEdit = (): void => {
    setName(dept.name);
    setKuerzel(dept.kuerzel ?? "");
    setAdGroups(dept.ad_groups);
    update.reset();
    setEditing(true);
  };

  const save = (): void => {
    if (!name.trim()) return;
    update.mutate(
      {
        id: dept.id,
        body: { name: name.trim(), kuerzel: kuerzel.trim() || null, ad_groups: adGroups },
      },
      { onSuccess: () => setEditing(false) },
    );
  };

  if (editing) {
    return (
      <li className="space-y-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("departments.name")}
            className="h-9 flex-1 rounded-md border border-input bg-background px-3 text-sm"
          />
          <input
            value={kuerzel}
            onChange={(e) => setKuerzel(e.target.value)}
            placeholder={t("departments.kuerzel")}
            className="h-9 w-32 rounded-md border border-input bg-background px-3 text-sm"
          />
        </div>
        <GroupPicker
          label={t("departments.groups_label")}
          hint={t("departments.groups_hint")}
          catalog={Array.isArray(groups.data) ? groups.data : []}
          selected={adGroups}
          onChange={setAdGroups}
        />
        <div className="flex items-center gap-2">
          <Button size="sm" disabled={update.isPending || !name.trim()} onClick={save}>
            {t("departments.save")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={update.isPending}
            onClick={() => setEditing(false)}
          >
            {t("common.cancel")}
          </Button>
          {update.isError ? (
            <span className="text-xs text-destructive">{t("departments.create_failed")}</span>
          ) : null}
        </div>
      </li>
    );
  }

  return (
    <li className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2">
        <Link
          to="/departments/$departmentId"
          params={{ departmentId: String(dept.id) }}
          className="truncate text-sm font-medium hover:underline"
        >
          {dept.name}
          {dept.kuerzel ? (
            <span className="ml-2 text-xs text-muted-foreground">{dept.kuerzel}</span>
          ) : null}
        </Link>
        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {t("departments.members_count", { count: dept.member_count })}
        </span>
        {dept.ad_groups.length > 0 ? (
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {t("departments.groups_count", { count: dept.ad_groups.length })}
          </span>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button variant="ghost" size="sm" onClick={startEdit}>
          {t("departments.edit")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={archive.isPending}
          onClick={() => archive.mutate(dept.id)}
        >
          {t("departments.archive")}
        </Button>
      </div>
    </li>
  );
}
