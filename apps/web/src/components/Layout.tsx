import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useCurrentUser, useLogout } from "@/api/hooks";
import { Button } from "@/components/ui/button";

export function Layout() {
  const { t } = useTranslation();
  const me = useCurrentUser();
  const logout = useLogout();

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container mx-auto flex items-center justify-between px-4 py-3">
          <Link to="/" className="font-serif text-lg font-semibold">
            {t("app.title")}
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link to="/classes" activeProps={{ className: "font-semibold underline" }}>
              {t("nav.classes")}
            </Link>
            <Link to="/users" activeProps={{ className: "font-semibold underline" }}>
              {t("nav.users")}
            </Link>
            {me.data?.is_admin ? (
              <Link to="/admin/settings" activeProps={{ className: "font-semibold underline" }}>
                {t("nav.admin")}
              </Link>
            ) : null}
            <Link to="/me" activeProps={{ className: "font-semibold underline" }}>
              {me.data?.upn ?? t("common.loading")}
            </Link>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              {t("nav.logout")}
            </Button>
          </nav>
        </div>
      </header>
      <main className="container mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
