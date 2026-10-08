import { get, post, put } from "./client";

/** Was die Installation eines Kunden zuletzt gemeldet hat (ADR-0024 D1). */
export interface StatusReport {
  reconcile: { ok: boolean; at: string; error: string | null; touched: boolean };
  effective_profile: string | null;
  enabled_modules: string[];
  ad: {
    configured: boolean;
    missing: string[];
    backend: string | null;
    last_success_at: string | null;
    last_failure_at: string | null;
    last_count: number | null;
    last_mode: string | null;
  } | null;
  sealed_public_key: string | null;
  sealed_key_id: string | null;
  secrets_present: Record<string, boolean>;
  /** Fehlt bei älteren Datenebenen. */
  local_admin?: {
    exists: boolean;
    enabled?: boolean | null;
    username?: string | null;
    mfa_enrolled?: boolean | null;
    locked?: boolean | null;
  } | null;
}

export interface TenantStatus {
  reported_at: string | null;
  report: StatusReport | null;
  console_profile: string;
  profile_matches: boolean | null;
}

export const getTenantStatus = (tenantId: string) =>
  get<TenantStatus>(`/api/tenants/${tenantId}/status`);

export interface SealedSecret {
  name: string;
  sealed: boolean;
  key_current: boolean | null;
  present_in_tenant: boolean | null;
  updated_at: string | null;
  updated_by: string | null;
}

export const listSealedSecrets = (tenantId: string) =>
  get<SealedSecret[]>(`/api/tenants/${tenantId}/sealed-secrets`);

export const putSealedSecret = (tenantId: string, name: string, value: string) =>
  put<SealedSecret[]>(`/api/tenants/${tenantId}/sealed-secrets/${name}`, { value });

export type MaintenanceAction = "demo_purge" | "audit_reset" | "local_admin_setup";
export type MaintenanceState = "requested" | "done" | "failed" | "cancelled";

export interface MaintenanceRequest {
  id: string;
  action: MaintenanceAction;
  state: MaintenanceState;
  reason: string;
  requested_by: string;
  requested_at: string;
  finished_at: string | null;
  result: Record<string, unknown> | null;
}

export const listMaintenance = (tenantId: string) =>
  get<MaintenanceRequest[]>(`/api/tenants/${tenantId}/maintenance`);

export const requestMaintenance = (
  tenantId: string,
  body: { action: MaintenanceAction; reason: string; confirm_slug: string },
) => post<MaintenanceRequest>(`/api/tenants/${tenantId}/maintenance`, body);

export const cancelMaintenance = (tenantId: string, requestId: string) =>
  post<MaintenanceRequest>(`/api/tenants/${tenantId}/maintenance/${requestId}/cancel`);

/** Lokales Admin-Konto im Portal einrichten oder Passwort setzen (versiegelt, einmalig). */
export const setupLocalAdmin = (
  tenantId: string,
  body: { username: string; password: string; reset_mfa: boolean },
) => post<MaintenanceRequest>(`/api/tenants/${tenantId}/local-admin`, body);
