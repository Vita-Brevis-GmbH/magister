import { ApiError, get, post } from "./client";

export type OffboardingState =
  | "requested"
  | "export_ready"
  | "dropped"
  | "shredded"
  | "purged"
  | "aborted";

export interface Offboarding {
  tenant_id: string;
  state: OffboardingState;
  reason: string;
  requested_by: string;
  requested_at: string;
  grace_days: number;
  grace_until: string;
  final_backup_id: string | null;
  export_job_id: string | null;
  export_delivered_at: string | null;
  dropped_at: string | null;
  dropped_by: string | null;
  approved_by: string | null;
  key_destroyed_at: string | null;
  key_destroyed_by: string | null;
  key_id: string | null;
  purge_due_at: string | null;
  purged_at: string | null;
  aborted_at: string | null;
  aborted_reason: string | null;
  updated_at: string;
  /**
   * Gesetzt, wenn ein Schritt geglückt ist, aber etwas daneben nicht.
   *
   * Konkret: der Kundenschlüssel ist vernichtet (unwiderruflich), die
   * Markierung für den Aufräumjob liess sich aber nicht schreiben. Dann läuft
   * eine Frist, die niemand einhält — das darf nicht in einer Protokollzeile
   * untergehen, deshalb zeigt die Oberfläche es als Warnung.
   */
  warning: string | null;
}

/**
 * Der Stand des Offboardings, oder `null`, wenn keines läuft.
 *
 * Die API antwortet mit 404, wenn für diesen Kunden nichts erfasst ist. Das
 * ist der Normalfall und kein Fehler — deshalb wird er hier zu `null` und
 * nicht zu einer roten Meldung.
 */
export async function getOffboarding(tenantId: string): Promise<Offboarding | null> {
  try {
    return await get<Offboarding>(`/api/tenants/${tenantId}/offboarding`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function startOffboarding(
  tenantId: string,
  body: { reason: string; requested_by: string; grace_days?: number },
): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding`, body);
}

export function recordExportDelivered(
  tenantId: string,
  exportId: string,
): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding/export/${exportId}`);
}

/** Unwiderruflich, und deshalb mit zwei verschiedenen Personen. */
export function dropTenantData(
  tenantId: string,
  body: { dropped_by: string; approved_by: string },
): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding/drop`, body);
}

export function confirmKeyDestroyed(
  tenantId: string,
  confirmedBy: string,
): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding/key-destroyed`, {
    confirmed_by: confirmedBy,
  });
}

export function markPurged(tenantId: string): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding/purged`);
}

export function abortOffboarding(tenantId: string, reason: string): Promise<Offboarding> {
  return post(`/api/tenants/${tenantId}/offboarding/abort`, { reason });
}

/** Die Reihenfolge, in der die Schritte gehen — für die Anzeige. */
export const OFFBOARDING_SEQUENCE: readonly OffboardingState[] = [
  "requested",
  "export_ready",
  "dropped",
  "shredded",
  "purged",
] as const;
