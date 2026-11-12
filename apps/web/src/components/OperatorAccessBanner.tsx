import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { CurrentUserOut } from "@/api/types";

/**
 * Der Balken, während jemand von Vita Brevis zusieht (ADR-0019 D6).
 *
 * Er geht an **jeden** angemeldeten Benutzer und nicht nur an Admins: eine
 * Transparenz, die nur derjenige sieht, der den Zugriff ohnehin bewilligt
 * hätte, ist keine. Wer arbeitet, während jemand zuschaut, soll das sehen und
 * nicht nachlesen müssen.
 *
 * Zwei Fassungen, weil zwei Leute auf denselben Balken schauen:
 *
 * * Der **Kunde** liest, wer zusieht, warum und bis wann.
 * * Der **Operator** liest, dass er in einer fremden Installation ist. Das ist
 *   kein Hinweis für den Kunden, sondern einer gegen den Irrtum, man sei
 *   gerade im eigenen Fenster.
 */
export function OperatorAccessBanner({ me }: { me: CurrentUserOut | undefined }) {
  const { t } = useTranslation();
  const access = me?.operator_active;
  if (!access) return null;

  const until = new Date(access.until).toLocaleTimeString("de-CH", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const mine = me?.is_operator ?? false;

  return (
    <div
      role="status"
      className={`border-b px-4 py-2 text-sm ${
        mine
          ? "border-sky-600/40 bg-sky-500/15 text-sky-950 dark:text-sky-100"
          : "border-amber-600/40 bg-amber-500/15 text-amber-950 dark:text-amber-100"
      }`}
    >
      <div className="container mx-auto flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">
          {mine ? t("operator.banner_self_title") : t("operator.banner_title")}
        </span>
        <span>
          {mine
            ? t("operator.banner_self_body", { until })
            : t("operator.banner_body", { operator: access.operator, until })}
        </span>
        <span className="text-xs opacity-80">
          {access.ticket
            ? t("operator.banner_reason_ticket", {
                ticket: access.ticket,
                reason: access.reason,
              })
            : t("operator.banner_reason", { reason: access.reason })}
        </span>
        {/* Der Weg zur Liste steht im Balken, weil der Balken der Ort ist, an
            dem die Frage entsteht. Ohne ihn müsste jemand ein Menü suchen,
            das ein Lehrer gar nicht hat. */}
        <Link to="/operator-accesses" className="ml-auto text-xs underline">
          {t("operator.banner_link")}
        </Link>
      </div>
    </div>
  );
}
