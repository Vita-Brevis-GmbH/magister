import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Was auf einer Seite steht, deren Fläche dem Betreiber gehört (ADR-0017 D1).
 *
 * Der Menüpunkt ist bei einer verwalteten Installation ausgeblendet — aber ein
 * Lesezeichen, ein Link in einer alten E-Mail oder die zurück-Taste führen
 * trotzdem hierher. Was dann kommt, entscheidet, ob jemand versteht, was los
 * ist:
 *
 * * Ein leeres Formular, das beim Speichern 404 sagt, ist die schlechteste
 *   Antwort — es sieht nach einem Fehler aus.
 * * Eine Weiterleitung auf die Startseite ist besser und lässt die Frage
 *   offen, warum.
 * * Ein Satz, der sagt WER es verwaltet und WIE man dorthin kommt, ist die
 *   Antwort. Deshalb dieser Baustein.
 */
export function ManagedByPlatform({ area }: { area: "settings" | "roles" }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t(`managed.${area}_title`)}</CardTitle>
        <CardDescription>{t(`managed.${area}_desc`)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        <p>{t("managed.who")}</p>
        <p>{t("managed.how")}</p>
      </CardContent>
    </Card>
  );
}
