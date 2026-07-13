/** Typed views of the backend's Pydantic response schemas. */

export interface CurrentUserOut {
  ad_object_guid: string;
  upn: string;
  given_name: string | null;
  surname: string | null;
  display_name: string | null;
  is_admin: boolean;
  school_scope: number[];
  roles: string[];
  expires_at: string;
}

export interface AuthCapabilities {
  oidc_enabled: boolean;
  local_login_enabled: boolean;
  ad_login_enabled: boolean;
}

export interface AdLoginRequest {
  login: string;
  password: string;
}

export type GrantableRole = "admin" | "schulleitung" | "smi";

export interface RoleAssignmentOut {
  ad_object_guid: string;
  role: string;
  school_id: number | null;
  school_name: string | null;
  granted_by: string | null;
  granted_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

export interface RoleGrantRequest {
  role: GrantableRole;
  school_id: number | null;
}

export interface LocalLoginRequest {
  username: string;
  password: string;
}

export interface LocalAdminOut {
  username: string;
  enabled: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  password_changed_at: string;
}

export interface LocalAdminPasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export type SchoolClassStatus = "active" | "archived";

export interface ClassOut {
  id: number;
  school_id: number;
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  details: string | null;
  status: SchoolClassStatus;
  created_at: string;
  updated_at: string;
}

export interface ClassCreate {
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  details?: string | null;
  school_id?: number;
}

export interface ClassUpdate {
  name?: string | null;
  kuerzel?: string | null;
  details?: string | null;
}

export interface SchoolOut {
  id: number;
  name: string;
  kuerzel: string;
  scope_short: string;
}

export type ClassTeacherRole = "haupt" | "co" | "stellvertretung";

export interface ClassTeacherOut {
  id: number;
  class_id: number;
  ad_object_guid: string;
  role: ClassTeacherRole;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

export interface ClassTeacherCreate {
  ad_object_guid: string;
  role: ClassTeacherRole;
  valid_from: string;
  valid_to?: string | null;
}

export interface SubjectTeacherOut {
  id: number;
  class_id: number;
  ad_object_guid: string;
  subject: string;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

export interface SubjectTeacherCreate {
  ad_object_guid: string;
  subject: string;
  valid_from: string;
  valid_to?: string | null;
}

export interface MyStudentBrief {
  ad_object_guid: string;
  display_name: string | null;
  upn: string | null;
}

export interface MyClassStudents {
  class_id: number;
  name: string;
  kuerzel: string | null;
  students: MyStudentBrief[];
}

export interface MyStudentsOut {
  classes: MyClassStudents[];
}

export interface ClassMembershipOut {
  id: number;
  class_id: number;
  ad_object_guid: string;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

export interface ClassMembershipCreate {
  ad_object_guid: string;
  valid_from?: string | null;
  valid_to?: string | null;
}

export interface ClassTeacherBrief {
  ad_object_guid: string;
  display_name: string | null;
  upn: string | null;
  role: ClassTeacherRole;
}

export interface UserClassOut {
  class_id: number;
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  teachers: ClassTeacherBrief[];
}

export interface UserDashboardOut {
  classes: UserClassOut[];
}

export interface AdUserOut {
  ad_object_guid: string;
  school_id: number | null;
  upn: string;
  sam_account_name: string | null;
  given_name: string | null;
  surname: string | null;
  display_name: string | null;
  mail: string | null;
  kind: "teacher" | "student" | "admin";
  enabled: boolean;
  last_sync_at: string | null;
  street_address: string | null;
  locality: string | null;
  postal_code: string | null;
  country: string | null;
  device_name: string | null;
  temp_device_name: string | null;
}

/** PATCH /users/{guid} — omit a field to leave it alone. Empty string/null
 *  clears (where the backend allows it). `upn` and `sam_account_name` are
 *  admin-only and must be non-empty when sent. */
export interface UserAttributesUpdate {
  display_name?: string | null;
  upn?: string | null;
  sam_account_name?: string | null;
  mail?: string | null;
  street_address?: string | null;
  locality?: string | null;
  postal_code?: string | null;
  country?: string | null;
  temp_device_name?: string | null;
}

/** PATCH /users/{guid}/status — enable/disable an AD account. */
export interface UserStatusUpdate {
  enabled: boolean;
  reason?: string | null;
}

export interface MailDomainsOut {
  domains: string[];
}

export interface AdUserListResponse {
  items: AdUserOut[];
  total: number;
  offset: number;
  limit: number;
  last_sync_at: string | null;
}

export type StudentPasswordResetMode = "generate" | "manual";

export interface StudentPasswordResetRequest {
  mode: StudentPasswordResetMode;
  manual_password?: string;
  force_change?: boolean;
}

export interface StudentPasswordResetResponse {
  mode: StudentPasswordResetMode;
  force_change: boolean;
  /** Set only when mode="generate"; never returned a second time. */
  temp_password: string | null;
}

export interface AppSettingsOut {
  version: number;
  oidc_issuer: string | null;
  oidc_client_id: string | null;
  oidc_client_secret_set: boolean;
  oidc_redirect_uri: string | null;
  oidc_scopes: string[];
  bootstrap_admins: string[];
  mail_domains: string[];
  ad_dcs: string[];
  ad_bind_mode: string;
  ad_bind_dn: string | null;
  ad_bind_password_set: boolean;
  ad_tls_verify: boolean;
  ad_tls_ca_pem: string | null;
  ad_login_enabled: boolean;
  ad_login_group: string | null;
  ad_users_search_base: string | null;
  ad_computers_search_base: string | null;
  ad_sync_interval_minutes: number;
  ad_ou_students_zyklus3: string | null;
  ad_ou_students_other: string | null;
  ad_ou_teachers: string | null;
  zyklus1_max_grade: number;
  zyklus2_max_grade: number;
  updated_at: string;
  updated_by_upn: string | null;
}

export interface AdConnectionTestOut {
  ok: boolean;
  detail: string;
}

export interface AdSyncResultOut {
  synced_count: number;
  school_partition: Record<string, number>;
}

export type AdUserOuKey = "teacher" | "student_zyklus3" | "student_other";

export interface AdUserCreateRequest {
  given_name: string;
  surname: string;
  sam_account_name: string;
  user_principal_name: string;
  mail?: string | null;
  ou_key: AdUserOuKey;
}

export interface AdUserCreateResponse {
  ad_object_guid: string;
  temp_password: string;
  force_change: boolean;
}

export interface AdUserDeleteResponse {
  ad_object_guid: string;
  ad_disabled: boolean;
}

export interface DemoPurgeResponse {
  found: boolean;
  schools: number;
  classes: number;
  users: number;
}

export type PrefLanguage = "de" | "fr" | "it" | "en";
export type PrefDateFormat = "DD.MM.YYYY" | "YYYY-MM-DD" | "MM/DD/YYYY";
export type PrefTimeFormat = "24h" | "12h";

export interface UserPreferencesOut {
  language: PrefLanguage;
  region: string;
  date_format: PrefDateFormat;
  time_format: PrefTimeFormat;
}

export type UserPreferencesUpdate = UserPreferencesOut;

/** Send `null`/omitted to leave fields untouched. The two secret fields are
 *  only updated when a non-empty string is sent — empty string is a no-op. */
export interface SubstitutionOut extends ClassTeacherOut {
  class_name: string;
  school_id: number | null;
}

export interface ClassPromotionRequest {
  target_class_id: number;
  archive_source: boolean;
  /** Subset of student GUIDs to move; omit to move all active students. */
  student_guids?: string[] | null;
}

export interface ClassPromotionError {
  ad_object_guid: string;
  detail: string;
}

export interface ClassPromotionResult {
  students_moved: number;
  students_failed: number;
  errors: ClassPromotionError[];
  source_archived: boolean;
}

export interface BulkClassMembershipCreate {
  students: ClassMembershipCreate[];
}

export interface BulkClassMembershipError {
  ad_object_guid: string;
  detail: string;
}

export interface BulkClassMembershipResult {
  added: number;
  memberships: ClassMembershipOut[];
  errors: BulkClassMembershipError[];
}

export interface AuditEventOut {
  id: number;
  ts: string;
  actor_upn: string | null;
  actor_object_guid: string | null;
  action: string;
  target_kind: string;
  target_id: string;
  school_id: number | null;
  ip: string | null;
  request_id: string;
  payload: Record<string, unknown>;
}

export interface AuditEventListResponse {
  items: AuditEventOut[];
  total: number;
  offset: number;
  limit: number;
}

export interface SubjectAccessReport {
  user: Record<string, unknown>;
  school: { id: number; name: string } | null;
  memberships: Array<Record<string, unknown>>;
  teacher_roles: Array<Record<string, unknown>>;
  audit_events: Array<{
    id: number;
    ts: string;
    action: string;
    target_kind: string;
    target_id: string;
    actor_upn: string | null;
    actor_object_guid: string | null;
    school_id: number | null;
    ip: string | null;
    request_id: string;
    payload: Record<string, unknown>;
    role: "actor" | "target";
  }>;
}

export interface StudentsByClassRow {
  class_id: number;
  school_id: number;
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  student_count: number;
}
export interface StudentsByClassReport {
  rows: StudentsByClassRow[];
  total_students: number;
  total_classes: number;
}

export interface TeacherWorkloadRow {
  ad_object_guid: string;
  upn: string | null;
  display_name: string | null;
  haupt_count: number;
  co_count: number;
  stellvertretung_count: number;
  total: number;
}
export interface TeacherWorkloadReport {
  rows: TeacherWorkloadRow[];
}

export interface ActivityRow {
  action: string;
  count: number;
}
export interface ActivityReport {
  since: string;
  rows: ActivityRow[];
}

export type LetterTemplate = "enrollment" | "class_change" | "password_handout";

export interface LetterRequest {
  student_guid: string;
  school_year?: string | null;
  first_day?: string | null;
  old_class_name?: string | null;
  effective_date?: string | null;
  temp_password?: string | null;
}

export type ImportKind = "classes" | "class_memberships" | "class_teachers" | "students";
export type ImportStatus = "staged" | "applied" | "cancelled";
export type ImportAction = "create" | "update" | "skip" | "error";

export interface ImportStagedRowOut {
  id: number;
  row_num: number;
  raw_data: Record<string, string>;
  action: ImportAction;
  errors: string[];
  applied_at: string | null;
  applied_error: string | null;
}

export interface ImportJobOut {
  id: number;
  school_id: number;
  kind: ImportKind;
  status: ImportStatus;
  filename: string | null;
  created_by_upn: string | null;
  created_at: string;
  applied_at: string | null;
  summary: Record<string, unknown>;
}

export interface ImportJobDetailOut extends ImportJobOut {
  rows: ImportStagedRowOut[];
  counts: Record<ImportAction, number>;
}

export interface ProvisionedCredential {
  upn: string;
  display_name: string;
  class_name: string;
  password: string;
  force_change: boolean;
}

export interface ImportApplyResult extends ImportJobDetailOut {
  credentials: ProvisionedCredential[];
}

export interface AppSettingsUpdate {
  oidc_issuer?: string | null;
  oidc_client_id?: string | null;
  oidc_client_secret?: string | null;
  oidc_redirect_uri?: string | null;
  oidc_scopes?: string[] | null;
  bootstrap_admins?: string[] | null;
  mail_domains?: string[] | null;
  ad_dcs?: string[] | null;
  ad_bind_mode?: string | null;
  ad_bind_dn?: string | null;
  ad_bind_password?: string | null;
  ad_tls_verify?: boolean | null;
  ad_tls_ca_pem?: string | null;
  ad_login_enabled?: boolean | null;
  ad_login_group?: string | null;
  ad_users_search_base?: string | null;
  ad_computers_search_base?: string | null;
  ad_sync_interval_minutes?: number | null;
  ad_ou_students_zyklus3?: string | null;
  ad_ou_students_other?: string | null;
  ad_ou_teachers?: string | null;
  zyklus1_max_grade?: number | null;
  zyklus2_max_grade?: number | null;
}
