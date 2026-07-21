import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { SchoolForm } from "./_app.admin.schools";

export const Route = createFileRoute("/_app/admin/schools/new")({
  component: NewSchoolPage,
});

function NewSchoolPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const back = (): void => {
    void navigate({ to: "/admin/schools" });
  };

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <Link to="/admin/schools" className="text-sm text-primary hover:underline">
          ← {t("schools.title")}
        </Link>
        <h1 className="font-serif text-2xl font-semibold">{t("schools.create_title")}</h1>
      </header>

      <SchoolForm target={null} onDone={back} />
    </div>
  );
}
