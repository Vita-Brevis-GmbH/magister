import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAssignZielgruppe, useGroupTemplates } from "@/api/hooks";
import type { ZielgruppeAssignResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

const selectClasses =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

/**
 * Konten einer Zielgruppe zuordnen — einzeln (Detailseite) oder als
 * Sammelaktion (Benutzerliste). Die Gruppen der bisherigen Zielgruppe fallen
 * weg, die der neuen kommen dazu; optional werden "darf nicht ändern",
 * "läuft nie ab" und der Tresor übernommen. Die Ablage-OU bleibt.
 */
export function ZielgruppeAssign({
  guids,
  schoolId,
  currentTemplateId,
  onDone,
}: {
  guids: string[];
  /** Standort der Konten: filtert die angebotenen Zielgruppen. */
  schoolId?: number | null;
  currentTemplateId?: number | null;
  onDone?: (results: ZielgruppeAssignResult[]) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const templatesQ = useGroupTemplates(schoolId ?? undefined);
  const assign = useAssignZielgruppe();
  const [templateId, setTemplateId] = useState(currentTemplateId ? String(currentTemplateId) : "");
  const [applySettings, setApplySettings] = useState(true);
  const [results, setResults] = useState<ZielgruppeAssignResult[] | null>(null);

  const templates = templatesQ.data ?? [];
  const ok = results?.filter((r) => r.ok) ?? [];
  const failed = results?.filter((r) => !r.ok) ?? [];
  const ouUnchanged = ok.filter((r) => r.ou_unchanged).length;
  const removed = ok.reduce((n, r) => n + r.removed.length, 0);

  function run(): void {
    if (!templateId || guids.length === 0) return;
    setResults(null);
    assign.mutate(
      { templateId: Number(templateId), guids, applySettings },
      {
        onSuccess: (res) => {
          setResults(res);
          onDone?.(res);
        },
      },
    );
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="zg-assign">{t("zielgruppe_assign.label")}</Label>
        <select
          id="zg-assign"
          className={selectClasses}
          value={templateId}
          onChange={(e) => {
            setTemplateId(e.target.value);
            setResults(null);
          }}
        >
          <option value="">{t("zielgruppe_assign.none")}</option>
          {templates.map((tpl) => (
            <option key={tpl.id} value={String(tpl.id)}>
              {tpl.name}
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-input"
          checked={applySettings}
          onChange={(e) => setApplySettings(e.target.checked)}
        />
        <span>
          {t("zielgruppe_assign.apply_settings")}
          <span className="block text-xs text-muted-foreground">
            {t("zielgruppe_assign.apply_settings_hint")}
          </span>
        </span>
      </label>
      <p className="text-xs text-muted-foreground">{t("zielgruppe_assign.groups_hint")}</p>
      <Button
        type="button"
        size="sm"
        disabled={!templateId || assign.isPending || guids.length === 0}
        onClick={run}
      >
        {assign.isPending
          ? t("common.loading")
          : t("zielgruppe_assign.submit", { count: guids.length })}
      </Button>
      {assign.isError ? (
        <p className="text-sm text-destructive">{t("zielgruppe_assign.failed")}</p>
      ) : null}
      {results ? (
        <div className="space-y-1 text-sm">
          <p>
            {t("zielgruppe_assign.result", {
              ok: ok.length,
              failed: failed.length,
              removed,
            })}
          </p>
          {ouUnchanged > 0 ? (
            <p className="text-amber-700 dark:text-amber-300">
              {t("zielgruppe_assign.ou_unchanged", { count: ouUnchanged })}
            </p>
          ) : null}
          {failed.length > 0 ? (
            <ul className="list-disc pl-5 text-destructive">
              {failed.map((f) => (
                <li key={f.ad_object_guid}>
                  {t(`zielgruppe_assign.err_${f.error ?? "unknown"}`, {
                    defaultValue: f.error ?? "",
                  })}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
