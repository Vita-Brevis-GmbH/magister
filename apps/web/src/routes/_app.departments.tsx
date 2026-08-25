import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useArchiveDepartment, useCreateDepartment, useDepartments, useSchools } from "@/api/hooks";
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
  const archive = useArchiveDepartment();
  const [name, setName] = useState("");
  const [kuerzel, setKuerzel] = useState("");
  const [schoolId, setSchoolId] = useState<number | "">("");

  const schoolList = useMemo(() => schools.data ?? [], [schools.data]);
  // Pre-select the org unit when there is exactly one to choose from.
  useEffect(() => {
    if (schoolId === "" && schoolList.length === 1) setSchoolId(schoolList[0].id);
  }, [schoolList, schoolId]);

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (!name.trim() || schoolId === "") return;
    create.mutate(
      { name: name.trim(), kuerzel: kuerzel.trim() || null, school_id: schoolId },
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
              onChange={(e) => setSchoolId(e.target.value ? Number(e.target.value) : "")}
              className="h-9 w-56 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">{t("departments.select_unit", { unit: terms.unit })}</option>
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
              <li key={d.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <Link
                  to="/departments/$departmentId"
                  params={{ departmentId: String(d.id) }}
                  className="text-sm font-medium hover:underline"
                >
                  {d.name}
                  {d.kuerzel ? (
                    <span className="ml-2 text-xs text-muted-foreground">{d.kuerzel}</span>
                  ) : null}
                </Link>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={archive.isPending}
                  onClick={() => archive.mutate(d.id)}
                >
                  {t("departments.archive")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
