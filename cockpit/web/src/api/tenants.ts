import { get, post } from "./client";

export type TenantStatus = "provisioning" | "active" | "suspended" | "archived";
/**
 * Dieselben drei Werte wie `cockpit_api.models.tenant.TenantProfile`.
 *
 * Hier stand vorher `school | municipality | demo`. Zwei davon gibt es in der
 * API nicht: „Gemeinde“ und „Demo“ waren im Formular wählbar und die Anlage
 * endete in einem 422. Aufgefallen beim Bauen der Vorlagen-Zielgruppe, die
 * dieselbe Liste braucht — und dabei die falsche mitgenommen hätte.
 */
export type TenantProfile = "school" | "company" | "neutral";
export type IsolationMode = "schema" | "database" | "cluster";

export interface Tenant {
  id: string;
  slug: string;
  name: string;
  customer_no: string | null;
  hostname: string;
  status: TenantStatus;
  profile: TenantProfile;
  isolation_mode: IsolationMode;
  dsn_ref: string;
  schema_name: string;
  db_role: string;
  schema_version: string | null;
  /** Nur die **Id** des Kundenschlüssels — nie der Schlüssel selbst. */
  audit_key_id: string | null;
  suspended_at: string | null;
  suspended_reason: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Ein Schritt des Bereitstellungs-Auftrags, wie das Protokoll ihn festhält.
 *
 * `ok` und nicht `status`: die API schreibt einen Wahrheitswert
 * (`services/provisioning.py::_entry`). Ein `status: string` wäre die
 * naheliegende Annahme und würde in der Anzeige lautlos zu „undefined“.
 */
export interface ProvisioningStep {
  step: string;
  ok: boolean;
  detail: string;
  at: string;
}

export interface ProvisioningJob {
  id: string;
  tenant_id: string;
  status: string;
  last_completed_step: string | null;
  steps: ProvisioningStep[];
  last_error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

/**
 * Ergebnis eines Bereitstellungslaufs.
 *
 * `role_password` und `data_key` kommen **genau einmal** — beim Anlegen
 * beziehungsweise beim Drehen. Danach sind sie über die API nicht mehr
 * abrufbar; die Oberfläche muss sie deshalb so zeigen, dass niemand sie
 * versehentlich wegklickt (siehe `SecretOnce`).
 */
export interface TenantProvisionResult {
  tenant: Tenant;
  job: ProvisioningJob;
  role_password: string | null;
  data_key: string | null;
  next_step: string | null;
}

export interface TenantCreate {
  slug: string;
  name: string;
  hostname: string;
  customer_no?: string | null;
  profile?: TenantProfile;
  isolation_mode?: IsolationMode;
}

export function listTenants(): Promise<Tenant[]> {
  return get("/api/tenants");
}

export function getTenant(id: string): Promise<TenantProvisionResult> {
  return get(`/api/tenants/${id}`);
}

export function createTenant(body: TenantCreate): Promise<TenantProvisionResult> {
  return post("/api/tenants", body);
}

/** Macht **ab der Abbruchstelle** weiter, nicht von vorn. */
export function resumeProvisioning(id: string): Promise<TenantProvisionResult> {
  return post(`/api/tenants/${id}/provisioning/resume`);
}

export function suspendTenant(id: string, reason: string): Promise<Tenant> {
  return post(`/api/tenants/${id}/suspend`, { reason });
}

export function unsuspendTenant(id: string): Promise<Tenant> {
  return post(`/api/tenants/${id}/unsuspend`);
}

export function rotateRolePassword(id: string): Promise<TenantProvisionResult> {
  return post(`/api/tenants/${id}/rotate-role-password`);
}
