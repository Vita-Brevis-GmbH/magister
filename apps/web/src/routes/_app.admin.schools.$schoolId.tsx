import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useSchool } from "@/api/hooks";
import { SchoolForm } from "./_app.admin.schools";

export const Route = createFileRoute("/_app/admin/schools/$schoolId")({
  component: EditSchoolPage,
});

function EditSchoolPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { schoolId } = Route.useParams();
  const id = Number(schoolId);
  const q = useSchool(Number.isNaN(id) ? 0 : id);

  const back = (): void => {
    void navigate({ to: "/admin/schools" });
  };

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <Link to="/admin/schools" className="text-sm text-primary hover:underline">
          ← {t("schools.title")}
        </Link>
        <h1 className="font-serif text-2xl font-semibold">
          {q.data ? q.data.name : t("schools.edit_title")}
        </h1>
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : q.data ? (
        <SchoolForm target={q.data} onDone={back} />
      ) : null}
    </div>
  );
}
