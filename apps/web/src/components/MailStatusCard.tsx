import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useMailStatus, useSendTestMail } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Stand des Mailversands und Testmail. Gehostet kommt die Anbindung aus der
 * Konsole — prüfen, ob sie funktioniert, soll der Kunden-Admin trotzdem.
 */
export function MailStatusCard(): JSX.Element {
  const { t } = useTranslation();
  const status = useMailStatus();
  const test = useSendTestMail();
  const [to, setTo] = useState("");
  const s = status.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.mail.title")}</CardTitle>
        <CardDescription>
          {t(s?.platform_managed ? "admin.mail.desc_managed" : "admin.mail.desc")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {status.isError ? (
          <p className="text-destructive">{t("errors.generic")}</p>
        ) : s ? (
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">{t("admin.mail.transport")}</dt>
              <dd>{t(`admin.mail.transport_${s.transport}`)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("admin.mail.sender")}</dt>
              <dd>
                {s.sender ? (s.sender_name ? `${s.sender_name} <${s.sender}>` : s.sender) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("admin.mail.state")}</dt>
              <dd className={s.ready ? "text-emerald-700" : "text-amber-700"}>
                {s.ready
                  ? t("admin.mail.ready")
                  : t("admin.mail.missing", { fields: s.missing.join(", ") })}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("admin.mail.reminder")}</dt>
              <dd>
                {s.expiry_notice_enabled
                  ? t("admin.mail.reminder_on", { days: s.expiry_notice_days.join(", ") })
                  : t("admin.mail.reminder_off")}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-muted-foreground">{t("common.loading")}</p>
        )}

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (to.trim()) test.mutate(to.trim());
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="mail-test-to">{t("admin.mail.test_to")}</Label>
            <Input
              id="mail-test-to"
              type="email"
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                test.reset();
              }}
              className="w-72"
            />
          </div>
          <Button type="submit" variant="outline" disabled={!to.trim() || test.isPending}>
            {test.isPending ? t("admin.mail.test_sending") : t("admin.mail.test_send")}
          </Button>
          {test.data ? (
            <span role="status" className={test.data.ok ? "text-emerald-700" : "text-destructive"}>
              {test.data.ok
                ? t("admin.mail.test_ok")
                : t("admin.mail.test_failed", { error: test.data.error ?? "" })}
            </span>
          ) : test.isError ? (
            <span className="text-destructive">{t("errors.generic")}</span>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}
