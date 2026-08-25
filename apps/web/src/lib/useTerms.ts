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

/**
 * Resolves the vocabulary for the active instance profile
 * (school / company / neutral). Falls back to "school" while the profile
 * loads, so labels never flash a missing-key string.
 */
export function useTerms(): TermSet {
  const { t } = useTranslation();
  const profile = useInstanceProfile().data ?? "school";
  const term = (k: string): string => t(`terms.${profile}.${k}`);
  return {
    unit: term("unit"),
    unit_plural: term("unit_plural"),
    group: term("group"),
    group_plural: term("group_plural"),
    lead: term("lead"),
    lead_plural: term("lead_plural"),
    member: term("member"),
    member_plural: term("member_plural"),
  };
}
