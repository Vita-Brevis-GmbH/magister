import { ApiError, authHeaders, get, post, put } from "./client";

export type BackupKind = "daily" | "monthly" | "pre_migration" | "manual" | "offboarding";
export type BackupStatus = "running" | "written" | "verified" | "failed" | "pruned";
export type RestoreState =
  | "requested"
  | "running"
  | "restored"
  | "switched"
  | "failed"
  | "discarded";
export type ExportState =
  | "requested"
  | "running"
  | "ready"
  | "downloaded"
  | "expired"
  | "failed";

export interface Backup {
  id: string;
  tenant_id: string;
  kind: BackupKind;
  status: BackupStatus;
  path: string;
  size_bytes: number | null;
  checksum_sha256: string | null;
  audit_key_id: string | null;
  schema_version: string | null;
  started_at: string;
  finished_at: string | null;
  verified_at: string | null;
  verify_detail: string | null;
  error: string | null;
}

export interface BackupPolicy {
  tenant_id: string;
  retention_days: number;
  pre_migration_retention_days: number;
  monthly_enabled: boolean;
  monthly_keep: number;
  rpo_hours: number;
  rto_hours: number;
  share_root: string | null;
  updated_at: string;
}

export type BackupPolicyUpdate = Partial<
  Pick<
    BackupPolicy,
    | "retention_days"
    | "pre_migration_retention_days"
    | "monthly_enabled"
    | "monthly_keep"
    | "rpo_hours"
    | "rto_hours"
    | "share_root"
  >
>;

export interface RestoreJob {
  id: string;
  tenant_id: string;
  backup_id: string;
  target_schema: string;
  state: RestoreState;
  reason: string;
  requested_by: string;
  approved_by: string | null;
  approved_at: string | null;
  switched_at: string | null;
  previous_schema: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ExportJob {
  id: string;
  tenant_id: string;
  state: ExportState;
  path: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
  requested_by: string;
  expires_at: string | null;
  downloaded_at: string | null;
  error: string | null;
  created_at: string;
}

export function listBackups(tenantId: string): Promise<Backup[]> {
  return get(`/api/tenants/${tenantId}/backups`);
}

export function createBackup(tenantId: string, kind: BackupKind): Promise<Backup> {
  return post(`/api/tenants/${tenantId}/backups`, { kind });
}

export function getBackupPolicy(tenantId: string): Promise<BackupPolicy> {
  return get(`/api/tenants/${tenantId}/backup-policy`);
}

export function updateBackupPolicy(
  tenantId: string,
  body: BackupPolicyUpdate,
): Promise<BackupPolicy> {
  return put(`/api/tenants/${tenantId}/backup-policy`, body);
}

export function listRestoreJobs(tenantId: string): Promise<RestoreJob[]> {
  return get(`/api/tenants/${tenantId}/restore-jobs`);
}

export function listExports(tenantId: string): Promise<ExportJob[]> {
  return get(`/api/tenants/${tenantId}/exports`);
}

export function requestExport(tenantId: string, requestedBy: string): Promise<ExportJob> {
  return post(`/api/tenants/${tenantId}/exports`, { requested_by: requestedBy });
}

/**
 * Export herunterladen.
 *
 * Ein einfacher `<a href>` geht hier **nicht**: der Endpunkt hängt am
 * Bootstrap-Token im `Authorization`-Header, und eine Navigation des Browsers
 * schickt keinen Header mit — sie endet in einem 401 und sieht aus wie ein
 * kaputter Export.
 *
 * Also über `fetch` und einen Blob. Der Preis ist ehrlich zu benennen: die
 * Datei liegt dabei vollständig im Speicher des Browsers. Für einen Export
 * einer Gemeinde (einige zehn Megabyte) ist das in Ordnung; für einen sehr
 * grossen Kunden wäre der richtige Weg ein kurzlebiger, signierter Link, den
 * die API noch nicht ausstellt. Dann ist der Weg über `magister-cli` mit
 * `curl` der bessere.
 */
export async function downloadExport(exportId: string, filename: string): Promise<void> {
  const response = await fetch(`/api/exports/${exportId}/download`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()).slice(0, 500));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    // Ohne revoke bleibt der Blob am Dokument hängen, bis der Tab geschlossen
    // wird — bei mehreren Exporten hintereinander summiert sich das.
    URL.revokeObjectURL(url);
  }
}
