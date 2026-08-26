import { useTranslation } from "react-i18next";

import { useInstanceProfile } from "@/api/hooks";

/** M6 term-pack: the instance vocabulary that varies by profile. */
export interface TermSet {
  unit: string;
  unit_plural: string;
  group: string;
  group_plural: string;
  lead: string;
  lead_plural: string;
  member: string;
  member_plural: string;
}

/** A `t()` with the active term-pack pre-injected as interpolation values. */
export type TermTranslate = (key: string, opts?: Record<string, unknown>) => string;

export interface Terms extends TermSet {
  /**
   * Like i18next's `t`, but with every term-pack variable ({{unit}},
   * {{unit_plural}}, {{group}}, {{lead}}, {{member}}, …) pre-injected. Use it
   * for any key in a SHARED module (devices, dashboard, reports, …) whose value
   * interpolates the instance vocabulary, so the label reads "Standort" in the
   * company edition and "Schule" in the school edition from ONE i18n string.
   * Caller-supplied `opts` win over the term vars.
   */
  tt: TermTranslate;
}

/**
 * Resolves the vocabulary for the active instance profile
 * (school / company / neutral). Falls back to "school" while the profile
 * loads, so labels never flash a missing-key string.
 */
export function useTerms(): Terms {
  const { t } = useTranslation();
  const profile = useInstanceProfile().data ?? "school";
  const term = (k: string): string => t(`terms.${profile}.${k}`);
  const set: TermSet = {
    unit: term("unit"),
    unit_plural: term("unit_plural"),
    group: term("group"),
    group_plural: term("group_plural"),
    lead: term("lead"),
    lead_plural: term("lead_plural"),
    member: term("member"),
    member_plural: term("member_plural"),
  };
  const tt: TermTranslate = (key, opts) => t(key, { ...set, ...opts });
  return { ...set, tt };
}
