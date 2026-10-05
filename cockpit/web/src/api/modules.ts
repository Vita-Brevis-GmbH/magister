import { get, put } from "./client";
import type { TenantProfile } from "./tenants";

/** Ein Modul, wie es beim Kunden gelten wird (`GET /api/tenants/{id}/modules`). */
export interface TenantModule {
  id: string;
  toggleable: boolean;
  enabled: boolean;
  default_in_profiles: string[];
  /** Ausdrücklich geschaltet, oder `null`, wenn das Profil entscheidet. */
  override: boolean | null;
}

export interface TenantModules {
  profile: TenantProfile;
  /** `override`: eine Abweichung in den Einstellungen überstimmt das Profil am Kunden. */
  profile_source: "tenant" | "override";
  known_profiles: TenantProfile[];
  modules: TenantModule[];
}

export interface TenantModulesUpdate {
  profile?: TenantProfile;
  module_overrides?: Record<string, boolean | null>;
}

export const getTenantModules = (tenantId: string) =>
  get<TenantModules>(`/api/tenants/${tenantId}/modules`);

export const putTenantModules = (tenantId: string, body: TenantModulesUpdate) =>
  put<TenantModules>(`/api/tenants/${tenantId}/modules`, body);
