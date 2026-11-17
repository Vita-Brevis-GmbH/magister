import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { customerPortalUrl } from "@/lib/customerPortal";

/**
 * „Kundenportal“ in der Kopfzeile: zurück zur Startseite des Kunden, wenn
 * Magister unter `<kunde>-um.<domain>` hinter dem Front-Proxy läuft (Anwender:
 * „Ein Shortcut wäre schön, wenn ich einfach wieder zu dem Kundenportal
 * gelangen könnte.“). Unter jedem anderen Namen kein Link.
 */
export function CustomerPortalLink({ hostname = window.location.hostname }: { hostname?: string }) {
  const { t } = useTranslation();
  const url = customerPortalUrl(hostname);
  if (!url) return null;
  return (
    <a
      href={url}
      title={t("nav.customer_portal_hint")}
      aria-label={t("nav.customer_portal")}
      className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      <span className="hidden md:inline">{t("nav.customer_portal")}</span>
    </a>
  );
}
