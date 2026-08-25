import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useDeleteDocumentTemplate,
  useDocumentTemplates,
  usePreviewDocumentTemplate,
  useSaveDocumentTemplate,
} from "@/api/hooks";
import type { DocumentTemplateOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/document-templates")({
  component: DocumentTemplatesPage,
});

function DocumentTemplatesPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useDocumentTemplates();
  const save = useSaveDocumentTemplate();
  const del = useDeleteDocumentTemplate();
  const preview = usePreviewDocumentTemplate();

  const meta = q.data?.meta;
  const [key, setKey] = useState("");
  const [language, setLanguage] = useState("de");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);

  // Default the key to the first available once the catalog loads.
  useEffect(() => {
    if (meta && !key && meta.keys.length > 0) setKey(meta.keys[0]);
  }, [meta, key]);

  // The stored global (school_id NULL) row for the current key/language.
  const existing: DocumentTemplateOut | undefined = useMemo(
    () =>
      q.data?.templates.find(
        (tpl) => tpl.key === key && tpl.language === language && tpl.school_id === null,
      ),
    [q.data, key, language],
  );

  // Load the stored row (or reset to blank) whenever the selection changes.
  useEffect(() => {
    setSubject(existing?.subject ?? "");
    setBody(existing?.body_html ?? "");
    setIsActive(existing?.is_active ?? true);
    setPreviewHtml(null);
    save.reset();
    del.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, language, existing?.id]);

  function onSave(): void {
    if (!key) return;
    save.mutate({
      key,
      language,
      school_id: null,
      subject: subject || null,
      body_html: body,
      is_active: isActive,
    });
  }

  function onPreview(): void {
    preview.mutate(
      { body_html: body, subject: subject || null },
      { onSuccess: (out) => setPreviewHtml(out.html) },
    );
  }

  function onDelete(): void {
    if (existing) del.mutate(existing.id);
  }

  function onLoadStarter(): void {
    const starter = meta?.starters[key];
    if (!starter) return;
    setSubject(starter.subject);
    setBody(starter.body_html);
    setPreviewHtml(null);
    save.reset();
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          {t("doc_templates.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("doc_templates.intro")}</p>
      </header>

      {q.isError ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {t("errors.generic")}
        </p>
      ) : q.isLoading || !meta ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="space-y-4 rounded-md border bg-card p-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="tpl-key">{t("doc_templates.key")}</Label>
                <select
                  id="tpl-key"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  {meta.keys.map((k) => (
                    <option key={k} value={k}>
                      {t(`doc_templates.key_${k}`, { defaultValue: k })}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpl-lang">{t("doc_templates.language")}</Label>
                <select
                  id="tpl-lang"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  {meta.languages.map((l) => (
                    <option key={l} value={l}>
                      {l.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="tpl-subject">{t("doc_templates.subject")}</Label>
              <Input
                id="tpl-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                maxLength={512}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="tpl-body">{t("doc_templates.body")}</Label>
              <textarea
                id="tpl-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={16}
                className="w-full rounded-md border border-input bg-background p-3 font-mono text-xs"
                placeholder="<p>{{ student.display_name }}</p>"
              />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
              />
              <span>{t("doc_templates.is_active")}</span>
            </label>

            {save.isError ? (
              <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {save.error.status === 422 ? t("doc_templates.error_invalid") : t("errors.generic")}
              </p>
            ) : null}
            {save.isSuccess ? (
              <p className="text-sm text-emerald-600">{t("doc_templates.saved")}</p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={onSave} disabled={save.isPending || !body.trim()}>
                {save.isPending ? t("doc_templates.saving") : t("doc_templates.save")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onPreview}
                disabled={preview.isPending || !body.trim()}
              >
                {t("doc_templates.preview")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onLoadStarter}
                disabled={!meta.starters[key]}
              >
                {t("doc_templates.load_starter")}
              </Button>
              {existing ? (
                <Button type="button" variant="ghost" onClick={onDelete} disabled={del.isPending}>
                  {t("doc_templates.reset_to_builtin")}
                </Button>
              ) : null}
            </div>

            <div className="rounded-md bg-muted/50 p-3 text-xs">
              <p className="mb-1 font-medium">{t("doc_templates.placeholders")}</p>
              <div className="flex flex-wrap gap-1">
                {meta.placeholders.map((p) => (
                  <code key={p} className="rounded bg-background px-1.5 py-0.5">
                    {`{{ ${p} }}`}
                  </code>
                ))}
              </div>
            </div>
          </section>

          <section className="space-y-2 rounded-md border bg-card p-4">
            <h2 className="text-sm font-medium">{t("doc_templates.preview_title")}</h2>
            {preview.isError ? (
              <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {t("doc_templates.error_invalid")}
              </p>
            ) : null}
            {previewHtml === null ? (
              <p className="text-sm text-muted-foreground">{t("doc_templates.preview_hint")}</p>
            ) : (
              <iframe
                title={t("doc_templates.preview_title")}
                sandbox=""
                srcDoc={previewHtml}
                className="h-[32rem] w-full rounded border bg-white"
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
