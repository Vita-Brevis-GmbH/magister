import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { ChevronDown, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCurrentUser, useLogout, useMyPreferences } from "@/api/hooks";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import i18n from "@/i18n";
import { displayLabel } from "@/lib/userDisplay";

export function Layout() {
  const { t } = useTranslation();
  const me = useCurrentUser();
  const logout = useLogout();
  const prefs = useMyPreferences();
  const qc = useQueryClient();
  // >0 while any query is refetching — drives the spinner on the refresh button.
  const fetching = useIsFetching();

  // Settings dropdown open state; closes on outside click or route change.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  // Apply the user's saved language once it loads (overrides browser default).
  useEffect(() => {
    if (prefs.data && i18n.language !== prefs.data.language) {
      void i18n.changeLanguage(prefs.data.language);
    }
  }, [prefs.data]);

  // Close the settings menu whenever the route changes.
  useEffect(() => {
    setSettingsOpen(false);
  }, [pathname]);

  // Close the settings menu on a click outside of it.
  useEffect(() => {
    if (!settingsOpen) return;
    function onDocMouseDown(e: MouseEvent): void {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [settingsOpen]);

  const navActive = "rounded-md bg-accent px-3 py-1.5 text-foreground";
  const navIdle = "rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground";
  const menuActive = "block rounded-md bg-accent px-3 py-2 text-sm text-foreground";
  const menuIdle =
    "block rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground";

  const isAdmin = me.data?.is_admin ?? false;
  const isSchulleitung = me.data?.roles.includes("schulleitung") ?? false;
  const isSmi = me.data?.roles.includes("smi") ?? false;
  const isTeacher = me.data?.kind === "teacher";
  // Anyone with a management capability can open the Einstellungen menu.
  const canManage = isAdmin || isSchulleitung || isSmi;

  return (
    <div className="min-h-screen bg-background">
      <header className="relative z-50 border-b bg-card/40 backdrop-blur supports-[backdrop-filter]:bg-card/60">
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
            {isTeacher ? (
              <Link
                to="/my-students"
                activeProps={{ className: navActive }}
                inactiveProps={{ className: navIdle }}
              >
                {t("nav.my_students")}
              </Link>
            ) : null}
            {isAdmin || isSmi ? (
              <Link
                to="/devices"
                activeProps={{ className: navActive }}
                inactiveProps={{ className: navIdle }}
              >
                {t("nav.devices")}
              </Link>
            ) : null}
            {canManage ? (
              <>
                <Link
                  to="/admin/imports"
                  activeProps={{ className: navActive }}
                  inactiveProps={{ className: navIdle }}
                >
                  {t("nav.imports")}
                </Link>
                <Link
                  to="/admin/reports"
                  activeProps={{ className: navActive }}
                  inactiveProps={{ className: navIdle }}
                >
                  {t("nav.reports")}
                </Link>
              </>
            ) : null}
            {canManage ? (
              <div className="relative" ref={settingsRef}>
                <button
                  type="button"
                  onClick={() => setSettingsOpen((v) => !v)}
                  aria-haspopup="menu"
                  aria-expanded={settingsOpen}
                  className={`flex items-center gap-1 ${settingsOpen ? navActive : navIdle}`}
                >
                  {t("nav.settings")}
                  <ChevronDown className="h-4 w-4" />
                </button>
                {settingsOpen ? (
                  <div
                    role="menu"
                    className="absolute right-0 top-full z-50 mt-1 w-56 rounded-md border bg-card p-1 shadow-md"
                  >
                    <Link
                      to="/users"
                      role="menuitem"
                      activeProps={{ className: menuActive }}
                      inactiveProps={{ className: menuIdle }}
                    >
                      {t("nav.usermanagement")}
                    </Link>
                    {isAdmin ? (
                      <Link
                        to="/admin/schools"
                        role="menuitem"
                        activeProps={{ className: menuActive }}
                        inactiveProps={{ className: menuIdle }}
                      >
                        {t("nav.schools")}
                      </Link>
                    ) : null}
                    <Link
                      to="/admin/audit"
                      role="menuitem"
                      activeProps={{ className: menuActive }}
                      inactiveProps={{ className: menuIdle }}
                    >
                      {t("nav.audit")}
                    </Link>
                    {isAdmin ? (
                      <Link
                        to="/admin/roles"
                        role="menuitem"
                        activeProps={{ className: menuActive }}
                        inactiveProps={{ className: menuIdle }}
                      >
                        {t("nav.roles")}
                      </Link>
                    ) : null}
                    <Link
                      to="/admin/substitutions"
                      role="menuitem"
                      activeProps={{ className: menuActive }}
                      inactiveProps={{ className: menuIdle }}
                    >
                      {t("nav.substitutions")}
                    </Link>
                    <Link
                      to="/admin/user-settings"
                      role="menuitem"
                      activeProps={{ className: menuActive }}
                      inactiveProps={{ className: menuIdle }}
                    >
                      {t("nav.user_settings")}
                    </Link>
                    {isAdmin ? (
                      <Link
                        to="/admin/settings"
                        role="menuitem"
                        activeProps={{ className: menuActive }}
                        inactiveProps={{ className: menuIdle }}
                      >
                        {t("nav.system_settings")}
                      </Link>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </nav>

          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void qc.invalidateQueries()}
              aria-busy={fetching > 0}
              title={t("nav.refresh")}
              aria-label={t("nav.refresh")}
            >
              <RefreshCw className={`h-4 w-4 ${fetching > 0 ? "animate-spin" : ""}`} />
              <span className="ml-1.5 hidden md:inline">{t("nav.refresh")}</span>
            </Button>
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
              variant="outline"
              onClick={() => logout.mutate()}
              aria-busy={logout.isPending}
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
