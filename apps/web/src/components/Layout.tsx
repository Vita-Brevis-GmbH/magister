import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useCurrentUser, useLogout } from "@/api/hooks";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import { displayLabel } from "@/lib/userDisplay";

export function Layout() {
  const { t } = useTranslation();
  const me = useCurrentUser();
  const logout = useLogout();
  const navActive = "rounded-md bg-accent px-3 py-1.5 text-foreground";
  const navIdle = "rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground";

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card/40 backdrop-blur supports-[backdrop-filter]:bg-card/60">
        <div className="container mx-auto flex h-14 items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2">
            <span className="font-serif text-lg font-semibold tracking-tight">
              {t("app.title")}
            </span>
          </Link>

          <nav className="flex items-center gap-1 text-sm font-medium">
            <Link
              to="/classes"
              activeProps={{ className: navActive }}
              inactiveProps={{ className: navIdle }}
            >
              {t("nav.classes")}
            </Link>
            <Link
              to="/users"
              activeProps={{ className: navActive }}
              inactiveProps={{ className: navIdle }}
            >
              {t("nav.users")}
            </Link>
            {me.data?.is_admin ? (
              <Link
                to="/admin/settings"
                activeProps={{ className: navActive }}
                inactiveProps={{ className: navIdle }}
              >
                {t("nav.admin")}
              </Link>
            ) : null}
            {me.data?.is_admin ||
            me.data?.roles.includes("schulleitung") ||
            me.data?.roles.includes("smi") ? (
              <>
                <Link
                  to="/admin/substitutions"
                  activeProps={{ className: navActive }}
                  inactiveProps={{ className: navIdle }}
                >
                  {t("nav.substitutions")}
                </Link>
                <Link
                  to="/admin/audit"
                  activeProps={{ className: navActive }}
                  inactiveProps={{ className: navIdle }}
                >
                  {t("nav.audit")}
                </Link>
              </>
            ) : null}
          </nav>

          <div className="flex items-center gap-3">
            {me.data ? (
              <Link
                to="/me"
                className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent"
              >
                <UserAvatar user={me.data} size="sm" />
                <span className="hidden md:inline">{displayLabel(me.data)}</span>
              </Link>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              {t("nav.logout")}
            </Button>
          </div>
        </div>
      </header>
      <main className="container mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
