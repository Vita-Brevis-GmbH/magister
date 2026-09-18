import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useOperatorAccesses } from "@/api/hooks";
import type { OperatorAccessOut } from "@/api/types";

export const Route = createFileRoute("/_app/operator-accesses")({
  component: OperatorAccessesPage,
});

function state(row: OperatorAccessOut): "running" | "ended" | "expired" {
  if (row.ended_at) return "ended";
  return new Date(row.expires_at) > new Date() ? "running" : "expired";
}

/**
 * „Zugriffe von Vita Brevis" (ADR-0019 D6).
 *
 * Ohne Rechteprüfung erreichbar: jeder angemeldete Benutzer darf hier
 * nachsehen. Die Seite enthält keine Personendaten des Kunden — nur, wer von
 * aussen zugesehen hat, wann und warum.
 */
function OperatorAccessesPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useOperatorAccesses();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          {t("operator.list_title")}
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">{t("operator.list_intro")}</p>
      </header>

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : q.isLoading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : q.data && q.data.length === 0 ? (
        // Der Normalfall bei einem Kunden, bei dem noch nie jemand drin war.
        // „Keine Einträge" ist hier eine gute Nachricht und soll auch so
        // klingen.
        <p className="rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground">
          {t("operator.list_empty")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">{t("operator.col_when")}</th>
                <th className="px-3 py-2 font-medium">{t("operator.col_who")}</th>
                <th className="px-3 py-2 font-medium">{t("operator.col_reason")}</th>
                <th className="px-3 py-2 font-medium">{t("operator.col_state")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data?.map((row) => (
                <tr key={row.jti} className="border-b last:border-0">
                  <td className="whitespace-nowrap px-3 py-2">
                    {new Date(row.started_at).toLocaleString("de-CH")}
                  </td>
                  <td className="px-3 py-2">{row.operator}</td>
                  <td className="px-3 py-2">
                    {row.ticket ? (
                      <span className="mr-1 rounded bg-muted px-1.5 py-0.5 text-xs">
                        {row.ticket}
                      </span>
                    ) : null}
                    {row.reason}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {t(`operator.state_${state(row)}`)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
