import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/operator/redeem")({
  component: OperatorRedeemPage,
});

interface RedeemOut {
  operator: string;
  reason: string;
  ticket: string | null;
  expires_at: string;
}

/**
 * Den Einlöseschein der Konsole gegen eine Sitzung tauschen (ADR-0019).
 *
 * Der Schein steht im **Fragment** der Adresse und nicht in der Abfrage: ein
 * Fragment wird nicht an den Server gesendet und erscheint damit in keinem
 * Zugriffslog und keinem Referer-Header. Er wird sofort aus der Adresszeile
 * entfernt — ein Schein im Verlauf des Browsers ist ein Schein, der in einem
 * Screenshot landet.
 */
function OperatorRedeemPage(): JSX.Element {
  const { t } = useTranslation();
  const [state, setState] = useState<"pending" | "ok" | "error">("pending");
  const [session, setSession] = useState<RedeemOut | null>(null);
  // Genau einmal einlösen. Ohne diese Sperre löst React im Entwicklungsmodus
  // (StrictMode) den Effekt zweimal aus — und der zweite Versuch scheitert,
  // weil der Schein verbraucht ist. Die Seite zeigte dann einen Fehler,
  // obwohl die Sitzung steht.
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const assertion = window.location.hash.replace(/^#/, "");
    // Sofort weg aus der Adresszeile, vor dem Netzaufruf.
    window.history.replaceState(null, "", window.location.pathname);
    if (!assertion) {
      setState("error");
      return;
    }
    apiFetch<RedeemOut>("/operator/redeem", { method: "POST", body: { assertion } })
      .then((out) => {
        setSession(out);
        setState("ok");
      })
      .catch(() => setState("error"));
  }, []);

  return (
    <div className="mx-auto flex min-h-screen max-w-lg items-center px-4">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>{t("operator.redeem_title")}</CardTitle>
          <CardDescription>
            {state === "pending"
              ? t("operator.redeem_pending")
              : state === "ok"
                ? t("operator.redeem_ok")
                : t("operator.redeem_error")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {state === "ok" && session ? (
            <>
              <dl className="space-y-1">
                <div className="flex gap-2">
                  <dt className="text-muted-foreground">{t("operator.col_who")}</dt>
                  <dd>{session.operator}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="text-muted-foreground">{t("operator.col_reason")}</dt>
                  <dd>
                    {session.ticket ? `${session.ticket} · ` : ""}
                    {session.reason}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="text-muted-foreground">{t("operator.until")}</dt>
                  <dd>{new Date(session.expires_at).toLocaleTimeString("de-CH")}</dd>
                </div>
              </dl>
              <p className="text-muted-foreground">{t("operator.redeem_readonly")}</p>
              {/* Ein harter Wechsel und kein Router-Link: die Sitzung ist neu,
                  und ein vollständiges Laden holt jeden Zwischenstand ab. */}
              <Button type="button" onClick={() => window.location.assign("/")}>
                {t("operator.redeem_enter")}
              </Button>
            </>
          ) : state === "error" ? (
            <p className="text-muted-foreground">{t("operator.redeem_error_hint")}</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
