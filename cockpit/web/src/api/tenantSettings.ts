import { del, get, put } from "./client";

/** Die Abweichungen eines Kunden von den Plattform-Vorgaben (ADR-0017). */
export interface TenantSettings {
  tenant_id: string;
  overrides: Record<string, unknown>;
  rbac: Record<string, string[]> | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface PlatformSettings {
  defaults: Record<string, unknown>;
  rbac: Record<string, string[]>;
  updated_at: string;
  updated_by: string | null;
}

export const getTenantSettings = (tenantId: string) =>
  get<TenantSettings>(`/api/tenants/${tenantId}/settings`);

export const putTenantSettings = (tenantId: string, overrides: Record<string, unknown>) =>
  put<TenantSettings>(`/api/tenants/${tenantId}/settings`, { overrides });

export const getPlatformSettings = () => get<PlatformSettings>("/api/platform/settings");

export const putPlatformDefaults = (defaults: Record<string, unknown>) =>
  put<PlatformSettings>("/api/platform/settings", { defaults });

/** Plattform-Geheimnisse (Standard-Mailversand), versiegelt für alle Kunden. */
export interface PlatformSecret {
  name: string;
  sealed: boolean;
  key_current: boolean | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface PlatformSecrets {
  platform_key_reported: boolean;
  secrets: PlatformSecret[];
}

export const listPlatformSecrets = () => get<PlatformSecrets>("/api/platform/sealed-secrets");

export const putPlatformSecret = (name: string, value: string) =>
  put<PlatformSecrets>(`/api/platform/sealed-secrets/${name}`, { value });

export const deletePlatformSecret = (name: string) =>
  del(`/api/platform/sealed-secrets/${name}`);
