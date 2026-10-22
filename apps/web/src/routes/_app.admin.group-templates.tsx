import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useAdGroups,
  useArchiveGroupTemplate,
  useCreateGroupTemplate,
  useEnsureDefaultGroupTemplates,
  useGroupTemplates,
  useInstanceProfile,
  useSchools,
  useUpdateGroupTemplate,
} from "@/api/hooks";
import type { GroupTemplateOut, PasswordProfile, SchoolOut, ZielgruppenOptions } from "@/api/types";
import { GroupPicker } from "@/components/GroupPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cleanOu, ouInUnit, ouValid } from "@/lib/ou";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/group-templates")({
  component: GroupTemplatesPage,
});

interface Draft extends ZielgruppenOptions {
  name: string;
  description: string;
  kind: string;
  ad_groups: string[];
  school_ids: number[];
  ad_ou: string;
}

// Kontoarten, die eine Zielgruppe festlegen kann (= ou_key beim Anlegen).
const SCHOOL_KINDS = ["teacher", "student_zyklus1", "student_zyklus2", "student_zyklus3"];
const PROFILES: PasswordProfile[] = ["readable", "teacher", "complex"];
// Kontoarten mit fester OU (die des Standorts) — sonst darf die Zielgruppe
// eine eigene Ziel-OU haben. Gleiche Liste wie FIXED_KINDS im Backend.
const FIXED_KINDS = [...SCHOOL_KINDS, "company"];

// Festes Passwort: nur dann legt Magister es im Tresor ab (wie password_stays
// im Backend). Sonst gäbe die Klassenliste bald ein falsches Passwort aus.
function passwordStays(d: ZielgruppenOptions): boolean {
  return !d.force_change && d.cannot_change_password && d.password_never_expires;
}

/** Schalter ändern; fällt das feste Passwort weg, geht der Tresor mit aus. */
function withVaultRule(d: Draft): Draft {
  return passwordStays(d) ? d : { ...d, store_password: false };
}

// Ziel-OU: sichtbar bei freier Kontoart oder ohne Standort; ohne Standort
// Pflicht (dort gibt es keine Standort-OU). Wie die API (services/group_templates.py).
function ouVisible(draft: Draft): boolean {
  return !FIXED_KINDS.includes(draft.kind) || draft.school_ids.length === 0;
}

function ouRequired(draft: Draft): boolean {
  return draft.school_ids.length === 0;
}

function ouMissing(draft: Draft): boolean {
  return ouRequired(draft) && cleanOu(draft.ad_ou) === "";
}

function ouInvalid(draft: Draft): boolean {
  return ouVisible(draft) && (!ouValid(draft.ad_ou) || ouMissing(draft));
}

const selectClasses =
  "flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

function emptyDraft(): Draft {
  return {
    name: "",
    description: "",
    kind: "",
    ad_groups: [],
    school_ids: [],
    password_profile: "complex",
    force_change: true,
    cannot_change_password: false,
    password_never_expires: false,
    store_password: false,
    ad_ou: "",
  };
}

function draftFrom(tpl: GroupTemplateOut): Draft {
  return {
    name: tpl.name,
    description: tpl.description ?? "",
    kind: tpl.kind ?? "",
    ad_groups: [...tpl.ad_groups],
    school_ids: [...tpl.school_ids],
    password_profile: (PROFILES as string[]).includes(tpl.password_profile)
      ? tpl.password_profile
      : "complex",
    force_change: tpl.force_change,
    cannot_change_password: tpl.cannot_change_password,
    password_never_expires: tpl.password_never_expires,
    store_password: tpl.store_password,
    ad_ou: tpl.ad_ou ?? "",
  };
}

function bodyFrom(draft: Draft) {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    // "custom" statt leer: das Backend behandelt nur bekannte Kontoarten als OU.
    kind: draft.kind || "custom",
    ad_groups: draft.ad_groups,
    school_ids: draft.school_ids,
    password_profile: draft.password_profile,
    force_change: draft.force_change,
    cannot_change_password: draft.cannot_change_password,
    password_never_expires: draft.password_never_expires,
    store_password: draft.store_password,
    // "" entfernt eine gesetzte Ziel-OU; bei fester Kontoart mit Standorten
    // gilt deren OU.
    ad_ou: ouVisible(draft) ? cleanOu(draft.ad_ou) : "",
  };
}

export function GroupTemplatesPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const q = useGroupTemplates();
  const schools = useSchools();
  const create = useCreateGroupTemplate();
  const catalog = useAdGroupsData();
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const schoolList = schools.data ?? [];

  function submit(): void {
    if (!draft.name.trim() || ouInvalid(draft)) return;
    create.mutate(bodyFrom(draft), { onSuccess: () => setDraft(emptyDraft()) });
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("group_templates.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("group_templates.intro", { unit_plural: terms.unit_plural })}
        </p>
      </header>

      <DefaultsCard schools={schoolList} />

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
          <Button
            onClick={submit}
            disabled={create.isPending || !draft.name.trim() || ouInvalid(draft)}
          >
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

// Fehlende Standard-Zielgruppen (Zyklus 1–3, Lehrperson) für einen Standort
// ergänzen — für Standorte von vor der Einführung oder nach dem Archivieren.
function DefaultsCard({ schools }: { schools: SchoolOut[] }): JSX.Element | null {
  const { t } = useTranslation();
  const terms = useTerms();
  const ensure = useEnsureDefaultGroupTemplates();
  const [schoolId, setSchoolId] = useState("");
  const selected = schoolId || (schools.length === 1 ? String(schools[0].id) : "");
  if (schools.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("group_templates.defaults_title")}</CardTitle>
        <CardDescription>
          {t("group_templates.defaults_desc", { unit: terms.unit })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <select
            aria-label={t("group_templates.schools_label", { unit_plural: terms.unit_plural })}
            className={selectClasses}
            value={selected}
            onChange={(e) => {
              setSchoolId(e.target.value);
              ensure.reset();
            }}
          >
            <option value="">—</option>
            {schools.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.name}
              </option>
            ))}
          </select>
          <Button
            className="shrink-0"
            disabled={!selected || ensure.isPending}
            onClick={() => ensure.mutate(Number(selected))}
          >
            {t("group_templates.defaults_button")}
          </Button>
        </div>
        {ensure.isError ? (
          <p className="text-sm text-destructive">{t("group_templates.defaults_failed")}</p>
        ) : ensure.data ? (
          <p className="text-sm text-muted-foreground">
            {ensure.data.length === 0
              ? t("group_templates.defaults_none")
              : t("group_templates.defaults_done", {
                  names: ensure.data.map((d) => d.name).join(", "),
                })}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
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
  const { tt } = terms;
  const isCompany = (useInstanceProfile().data ?? "school") === "company";
  const kinds = isCompany ? ["company"] : SCHOOL_KINDS;

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
      <div className="space-y-1">
        <Label htmlFor="tpl-kind">{t("group_templates.kind_label")}</Label>
        <select
          id="tpl-kind"
          className={selectClasses}
          value={draft.kind}
          onChange={(e) => onChange({ ...draft, kind: e.target.value })}
        >
          <option value="">{t("group_templates.kind_none")}</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {tt(`admin.user_new.ou_${k}`)}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="tpl-profile">{t("group_templates.profile_label")}</Label>
        <select
          id="tpl-profile"
          className={selectClasses}
          value={draft.password_profile}
          onChange={(e) =>
            onChange({ ...draft, password_profile: e.target.value as PasswordProfile })
          }
        >
          {PROFILES.map((p) => (
            <option key={p} value={p}>
              {t(`group_templates.profile_${p}`)}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{t("group_templates.profile_hint")}</p>
      </div>
      <fieldset className="space-y-2 rounded-md border p-3">
        <legend className="px-1 text-sm font-medium">{t("group_templates.options_label")}</legend>
        <Check
          checked={draft.force_change}
          onChange={(v) => onChange(withVaultRule({ ...draft, force_change: v }))}
          label={t("group_templates.opt_force_change")}
        />
        <Check
          checked={!draft.cannot_change_password}
          onChange={(v) => onChange(withVaultRule({ ...draft, cannot_change_password: !v }))}
          label={t("group_templates.opt_can_change")}
        />
        <Check
          checked={draft.password_never_expires}
          onChange={(v) => onChange(withVaultRule({ ...draft, password_never_expires: v }))}
          label={t("group_templates.opt_never_expires")}
        />
        <Check
          checked={draft.store_password}
          disabled={!passwordStays(draft)}
          onChange={(v) => onChange({ ...draft, store_password: v })}
          label={t("group_templates.opt_store")}
          hint={t("group_templates.opt_store_hint")}
        />
      </fieldset>
      <GroupPicker
        label={t("group_templates.groups_label")}
        hint={t("group_templates.groups_hint")}
        catalog={catalog}
        selected={draft.ad_groups}
        onChange={(next) => onChange({ ...draft, ad_groups: next })}
      />
      <div className="space-y-1">
        <Label>
          {t("group_templates.schools_label_optional", { unit_plural: terms.unit_plural })}
        </Label>
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
      {ouVisible(draft) ? <OuField draft={draft} onChange={onChange} schools={schools} /> : null}
    </div>
  );
}

/** Ziel-OU der Zielgruppe — unter den Standorten; ohne Standort Pflicht. */
function OuField({
  draft,
  onChange,
  schools,
}: {
  draft: Draft;
  onChange: (d: Draft) => void;
  schools: SchoolOut[];
}): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const ou = cleanOu(draft.ad_ou);
  const required = ouRequired(draft);
  // Dieselbe Regel wie der AD-Abgleich: OU=<Kürzel> muss im DN vorkommen,
  // sonst ordnet er das Konto keinem Standort zu. Magister lehnt die Anlage
  // an solchen Standorten ab — hier sieht man es vorher.
  const offered = schools.filter((s) => draft.school_ids.includes(s.id));
  const outside = ou && ouValid(ou) ? offered.filter((s) => !ouInUnit(ou, s.scope_short)) : [];
  return (
    <div className="space-y-1">
      <Label htmlFor="tpl-ou">
        {required ? t("group_templates.ou_label_required") : t("group_templates.ou_label")}
      </Label>
      <Input
        id="tpl-ou"
        value={draft.ad_ou}
        onChange={(e) => onChange({ ...draft, ad_ou: e.target.value })}
        placeholder={t("group_templates.ou_placeholder")}
        maxLength={512}
        required={required}
      />
      <p className="text-xs text-muted-foreground">
        {required
          ? t("group_templates.ou_hint_required", {
              unit: terms.unit,
              unit_plural: terms.unit_plural,
            })
          : t("group_templates.ou_hint", { unit: terms.unit })}
      </p>
      {ouMissing(draft) ? (
        <p className="text-xs text-destructive">
          {t("group_templates.ou_required", { unit: terms.unit })}
        </p>
      ) : !ouValid(draft.ad_ou) ? (
        <p className="text-xs text-destructive">{t("group_templates.ou_invalid")}</p>
      ) : null}
      {outside.length > 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {t("group_templates.ou_outside", {
            names: outside.map((s) => s.name).join(", "),
            unit: terms.unit,
          })}
        </p>
      ) : null}
    </div>
  );
}

function Check({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}): JSX.Element {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-input"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
    </label>
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
  const [draft, setDraft] = useState<Draft>(() => draftFrom(tpl));

  function startEdit(): void {
    setDraft(draftFrom(tpl));
    update.reset();
    setEditing(true);
  }

  function save(): void {
    if (!draft.name.trim() || ouInvalid(draft)) return;
    update.mutate({ id: tpl.id, body: bodyFrom(draft) }, { onSuccess: () => setEditing(false) });
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
              <Button
                size="sm"
                disabled={update.isPending || !draft.name.trim() || ouInvalid(draft)}
                onClick={save}
              >
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
                {SCHOOL_KINDS.includes(tpl.kind ?? "") || tpl.kind === "company"
                  ? `${terms.tt(`admin.user_new.ou_${tpl.kind}`)} · `
                  : null}
                {t(`group_templates.profile_short_${tpl.password_profile}`)}
                {tpl.ad_ou ? ` · ${t("group_templates.ou_badge", { ou: tpl.ad_ou })}` : null}
                {tpl.store_password && passwordStays(tpl)
                  ? ` · ${t("group_templates.badge_stored")}`
                  : null}{" "}
                · {t("group_templates.count_groups", { count: tpl.ad_groups.length })} ·{" "}
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
