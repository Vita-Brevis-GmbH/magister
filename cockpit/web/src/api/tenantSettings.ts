import { get, put } from "./client";

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
