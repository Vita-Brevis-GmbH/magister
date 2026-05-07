import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useCurrentUser } from "@/api/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/")({
  component: DashboardPage,
});

function DashboardPage(): JSX.Element {
  const { t } = useTranslation();
  const me = useCurrentUser();
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("app.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("app.tagline")}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("auth.logged_in_as")}</CardTitle>
          <CardDescription>{me.data?.upn ?? t("common.loading")}</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("auth.roles")}: {me.data?.roles.length ? me.data.roles.join(", ") : t("auth.no_roles")}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Link to="/classes" className="block">
          <Card className="transition hover:bg-accent hover:text-accent-foreground">
            <CardHeader>
              <CardTitle className="text-base">{t("nav.classes")}</CardTitle>
            </CardHeader>
          </Card>
        </Link>
        <Link to="/users" className="block">
          <Card className="transition hover:bg-accent hover:text-accent-foreground">
            <CardHeader>
              <CardTitle className="text-base">{t("nav.users")}</CardTitle>
            </CardHeader>
          </Card>
        </Link>
      </div>
    </div>
  );
}
