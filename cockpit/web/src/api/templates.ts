import { del, get, put } from "./client";
import type { TenantProfile } from "./tenants";

/** An wen sich eine Vorlage richtet (ADR-0018 D5). */
export type TemplateAudience = "all" | "profile" | "selection";

export interface PlatformTemplate {
  key: string;
  language: string;
  subject: string | null;
  body_html: string;
  /** `false` = die Fassung gilt beim Kunden auch dann, wenn er eine eigene hat. */
  may_override: boolean;
  /** Steigt nur bei einer inhaltlichen Änderung (ADR-0018 D4). */
  version: number;
  audience: TemplateAudience;
  audience_profile: TenantProfile | null;
  is_active: boolean;
  /** Bei `audience = "selection"` die gewählten Kunden, sonst leer. */
  tenant_ids: string[];
  updated_at: string;
  updated_by: string | null;
}

export interface PlatformTemplateList {
  items: PlatformTemplate[];
  /** Die Schlüssel und Sprachen kommen von der API, damit die Liste nicht doppelt gepflegt wird. */
  keys: string[];
  languages: string[];
}

export interface PlatformTemplateSave {
  subject: string | null;
  body_html: string;
  may_override: boolean;
  audience: TemplateAudience;
  audience_profile: TenantProfile | null;
  /** `null` = Auswahl nicht anfassen, `[]` = Auswahl leeren. */
  tenant_ids: string[] | null;
  is_active: boolean;
  actor: string;
}

export function listPlatformTemplates(): Promise<PlatformTemplateList> {
  return get("/api/platform/templates");
}

export function savePlatformTemplate(
  key: string,
  language: string,
  body: PlatformTemplateSave,
): Promise<PlatformTemplate> {
  return put(`/api/platform/templates/${key}/${language}`, body);
}

export function deletePlatformTemplate(key: string, language: string): Promise<void> {
  return del(`/api/platform/templates/${key}/${language}`);
}
