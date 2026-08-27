import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useAdGroups,
  useArchiveGroupTemplate,
  useCreateGroupTemplate,
  useGroupTemplates,
  useSchools,
  useUpdateGroupTemplate,
} from "@/api/hooks";
import type { GroupTemplateOut, SchoolOut } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/group-templates")({
  component: GroupTemplatesPage,
});

interface Draft {
  name: string;
  description: string;
  ad_groups: string[];
  school_ids: number[];
}

function emptyDraft(): Draft {
  return { name: "", description: "", ad_groups: [], school_ids: [] };
}

function GroupTemplatesPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const q = useGroupTemplates();
  const schools = useSchools();
  const create = useCreateGroupTemplate();
  const catalog = useAdGroupsData();
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const schoolList = schools.data ?? [];

  function submit(): void {
    if (!draft.name.trim()) return;
    create.mutate(
      {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        ad_groups: draft.ad_groups,
        school_ids: draft.school_ids,
      },
      { onSuccess: () => setDraft(emptyDraft()) },
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("group_templates.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("group_templates.intro", { unit_plural: terms.unit_plural })}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("group_templates.new_title")}</CardTitle>
          <CardDescription>{t("group_templates.new_desc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <TemplateFields
            draft={draft}
            onChange={setDraft}
            schools={schoolList}
            catalog={catalog}
          />
          {create.isError ? (
            <p className="text-sm text-destructive">{t("group_templates.create_failed")}</p>
          ) : null}
          <Button onClick={submit} disabled={create.isPending || !draft.name.trim()}>
            {t("group_templates.create")}
          </Button>
        </CardContent>
      </Card>

      {q.isError ? (
        <p className="text-sm text-destructive">{t("errors.generic")}</p>
      ) : q.isLoading || !q.data ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : q.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("group_templates.empty")}</p>
      ) : (
        <div className="space-y-3">
          {q.data.map((tpl) => (
            <TemplateRow key={tpl.id} tpl={tpl} schools={schoolList} />
          ))}
        </div>
      )}
    </div>
  );
}

// Small wrapper so the AD-group catalog is fetched once at page level and the
// hook rule (top-level call) is respected.
function useAdGroupsData() {
  return useAdGroups().data ?? [];
}

function TemplateFields({
  draft,
  onChange,
  schools,
  catalog,
}: {
  draft: Draft;
  onChange: (d: Draft) => void;
  schools: SchoolOut[];
  catalog: ReturnType<typeof useAdGroupsData>;
}): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();

  function toggleSchool(id: number, checked: boolean): void {
    onChange({
      ...draft,
      school_ids: checked ? [...draft.school_ids, id] : draft.school_ids.filter((s) => s !== id),
    });
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <Label>{t("group_templates.name")}</Label>
        <Input
          value={draft.name}
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
          placeholder={t("group_templates.name_placeholder")}
          maxLength={80}
        />
      </div>
      <div className="space-y-1">
        <Label>{t("group_templates.description")}</Label>
        <Input
          value={draft.description}
          onChange={(e) => onChange({ ...draft, description: e.target.value })}
          maxLength={2000}
        />
      </div>
      <GroupPicker
        label={t("group_templates.groups_label")}
        hint={t("group_templates.groups_hint")}
        catalog={catalog}
        selected={draft.ad_groups}
        onChange={(next) => onChange({ ...draft, ad_groups: next })}
      />
      <div className="space-y-1">
        <Label>{t("group_templates.schools_label", { unit_plural: terms.unit_plural })}</Label>
        <p className="text-xs text-muted-foreground">
          {draft.school_ids.length === 0
            ? t("group_templates.schools_global_hint", { unit_plural: terms.unit_plural })
            : t("group_templates.schools_hint", { unit_plural: terms.unit_plural })}
        </p>
        <div className="flex flex-wrap gap-3 rounded-md border p-2">
          {schools.length === 0 ? (
            <span className="text-xs text-muted-foreground">
              {t("group_templates.no_schools", { unit_plural: terms.unit_plural })}
            </span>
          ) : (
            schools.map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-input"
                  checked={draft.school_ids.includes(s.id)}
                  onChange={(e) => toggleSchool(s.id, e.target.checked)}
                />
                <span>{s.name}</span>
              </label>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function TemplateRow({
  tpl,
  schools,
}: {
  tpl: GroupTemplateOut;
  schools: SchoolOut[];
}): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const update = useUpdateGroupTemplate();
  const archive = useArchiveGroupTemplate();
  const catalog = useAdGroupsData();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => ({
    name: tpl.name,
    description: tpl.description ?? "",
    ad_groups: [...tpl.ad_groups],
    school_ids: [...tpl.school_ids],
  }));

  function startEdit(): void {
    setDraft({
      name: tpl.name,
      description: tpl.description ?? "",
      ad_groups: [...tpl.ad_groups],
      school_ids: [...tpl.school_ids],
    });
    update.reset();
    setEditing(true);
  }

  function save(): void {
    if (!draft.name.trim()) return;
    update.mutate(
      {
        id: tpl.id,
        body: {
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          ad_groups: draft.ad_groups,
          school_ids: draft.school_ids,
        },
      },
      { onSuccess: () => setEditing(false) },
    );
  }

  const scopeLabel =
    tpl.school_ids.length === 0
      ? t("group_templates.global_badge")
      : schools
          .filter((s) => tpl.school_ids.includes(s.id))
          .map((s) => s.name)
          .join(", ");

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        {editing ? (
          <>
            <TemplateFields draft={draft} onChange={setDraft} schools={schools} catalog={catalog} />
            {update.isError ? (
              <p className="text-sm text-destructive">{t("group_templates.create_failed")}</p>
            ) : null}
            <div className="flex gap-2">
              <Button size="sm" disabled={update.isPending || !draft.name.trim()} onClick={save}>
                {t("group_templates.save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={update.isPending}
                onClick={() => setEditing(false)}
              >
                {t("common.cancel")}
              </Button>
            </div>
          </>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <p className="font-medium">{tpl.name}</p>
              {tpl.description ? (
                <p className="text-sm text-muted-foreground">{tpl.description}</p>
              ) : null}
              <p className="text-xs text-muted-foreground">
                {t("group_templates.count_groups", { count: tpl.ad_groups.length })} ·{" "}
                <span
                  title={t("group_templates.schools_label", { unit_plural: terms.unit_plural })}
                >
                  {scopeLabel}
                </span>
              </p>
            </div>
            <div className="flex shrink-0 gap-1">
              <Button variant="ghost" size="sm" onClick={startEdit}>
                {t("group_templates.edit")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={archive.isPending}
                onClick={() => archive.mutate(tpl.id)}
              >
                {t("group_templates.archive")}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
