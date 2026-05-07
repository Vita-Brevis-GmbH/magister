import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useCurrentUser } from "@/api/hooks";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/me")({
  component: MePage,
});

function MePage(): JSX.Element {
  const { t } = useTranslation();
  const me = useCurrentUser();
  if (me.isLoading || !me.data) return <p>{t("common.loading")}</p>;
  const u = me.data;
  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle className="font-serif">{t("me.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <Row label={t("auth.logged_in_as")} value={u.upn} />
        <Row label="ad_object_guid" value={u.ad_object_guid} mono />
        <Row
          label={t("auth.roles")}
          value={u.roles.length ? u.roles.join(", ") : t("auth.no_roles")}
        />
        <Row
          label={t("auth.school_scope")}
          value={u.school_scope.length ? u.school_scope.join(", ") : "–"}
        />
        <Row label={t("auth.expires_at")} value={u.expires_at} mono />
      </CardContent>
    </Card>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}): JSX.Element {
  return (
    <div className="flex flex-wrap gap-x-4">
      <span className="text-muted-foreground">{label}:</span>
      <span className={mono ? "font-mono" : undefined}>{value}</span>
    </div>
  );
}
