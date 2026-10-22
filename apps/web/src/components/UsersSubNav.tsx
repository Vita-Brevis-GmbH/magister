import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

const tab = "rounded px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground";
const tabActive = "rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground";

/** Unterpunkte im Bereich Benutzer: die Übersicht und der Passwort-Ablauf. */
export function UsersSubNav(): JSX.Element {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t("users.subnav_label")}
      className="inline-flex flex-wrap rounded-md border bg-background p-0.5"
    >
      <Link
        to="/users"
        activeOptions={{ exact: true }}
        activeProps={{ className: tabActive }}
        inactiveProps={{ className: tab }}
      >
        {t("users.subnav_overview")}
      </Link>
      <Link
        to="/password-expiry"
        activeProps={{ className: tabActive }}
        inactiveProps={{ className: tab }}
      >
        {t("users.subnav_password_expiry")}
      </Link>
    </nav>
  );
}
