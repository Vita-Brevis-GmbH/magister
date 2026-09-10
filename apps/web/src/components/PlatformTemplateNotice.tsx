import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAcknowledgePlatformTemplate } from "@/api/hooks";
import type { DocumentTemplateOut, PlatformTemplateOut } from "@/api/types";
import { Button } from "@/components/ui/button";

/**
 * Was der Betreiber zu dieser Vorlage geliefert hat (ADR-0018).
 *
 * Drei Lagen, und jede braucht einen anderen Satz:
 *
 * * **Gesperrt.** Die Fassung des Betreibers gilt. Der eigene Text bleibt
 *   sichtbar und liegt bereit — er ist nicht gelöscht, und das muss dastehen,
 *   sonst sieht die Seite nach Datenverlust aus.
 * * **Neue Fassung da, eigener Text vorhanden.** Der Hinweis mit dem Text zum
 *   Nachlesen und einem Knopf „gesehen“. Ohne den Text wäre der Hinweis eine
 *   Aufforderung, beim Betreiber nachzufragen.
 * * **Fassung da, kein eigener Text.** Dann gilt sie ohnehin; hier steht nur,
 *   woher der Text kommt.
 */
export function PlatformTemplateNotice({
  platform,
  own,
}: {
  platform: PlatformTemplateOut | undefined;
  own: DocumentTemplateOut | undefined;
}) {
  const { t } = useTranslation();
  const ack = useAcknowledgePlatformTemplate();
  const [open, setOpen] = useState(false);

  if (!platform) return null;

  const locked = !platform.may_override;
  // Quittiert wird nur, was auch zur Entscheidung steht. Bei einer Sperre
  // gilt die Fassung des Betreibers ohnehin — ein Knopf „Gesehen“ unter einer
  // Überschrift, die von keiner neuen Fassung spricht, quittiert etwas, das
  // die Seite nicht anzeigt. Der Hinweis kommt zurück, sobald die Sperre
  // aufgehoben wird, und dann ist er richtig.
  const updateAvailable = !locked && (own?.platform_update_available ?? false);
  const tone = locked
    ? "border-amber-500/50 bg-amber-500/10"
    : updateAvailable
      ? "border-sky-500/50 bg-sky-500/10"
      : "border-border bg-muted/40";

  return (
    <div className={`space-y-2 rounded-md border px-3 py-2 text-sm ${tone}`}>
      <p className="font-medium">
        {locked
          ? t("platform_tpl.locked_title")
          : updateAvailable
            ? t("platform_tpl.update_title")
            : t("platform_tpl.applies_title")}
      </p>
      <p className="text-muted-foreground">
        {locked
          ? t("platform_tpl.locked_desc")
          : updateAvailable
            ? t("platform_tpl.update_desc", { version: platform.version })
            : t("platform_tpl.applies_desc")}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? t("platform_tpl.hide") : t("platform_tpl.show")}
        </Button>
        {updateAvailable && own ? (
          <Button
            type="button"
            size="sm"
            onClick={() => ack.mutate(own.id)}
            disabled={ack.isPending}
          >
            {ack.isPending ? t("platform_tpl.acknowledging") : t("platform_tpl.acknowledge")}
          </Button>
        ) : null}
      </div>
      {ack.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : null}
      {open ? (
        <div className="space-y-1 rounded bg-background/70 p-2">
          {platform.subject ? (
            <p className="text-xs">
              <span className="text-muted-foreground">{t("doc_templates.subject")}: </span>
              {platform.subject}
            </p>
          ) : null}
          {/* Als Quelltext und nicht gerendert: hier steht, was der Betreiber
              geschickt hat, und ein Vergleich mit dem eigenen Text im Feld
              darunter ist nur so möglich. Die Vorschau ist der Ort fürs
              Ansehen. */}
          <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs">
            {platform.body_html}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
