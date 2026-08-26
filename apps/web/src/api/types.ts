/** Typed views of the backend's Pydantic response schemas. */

export interface CurrentUserOut {
  ad_object_guid: string;
  upn: string;
  given_name: string | null;
  surname: string | null;
  display_name: string | null;
  is_admin: boolean;
  /** AD classification: teacher | student | admin. null for the local admin. */
  kind: "teacher" | "student" | "admin" | null;
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

// Built-in role keys still used for i18n label lookup; custom roles carry their
// own name from the RBAC config (ADR-0010), so grants accept any role string.
export type GrantableRole = string;

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

// --- Dynamic roles + rights matrix (ADR-0010, /admin/rbac) -----------------
export interface RbacRole {
  key: string;
  name: string;
  is_system: boolean;
  is_admin: boolean;
  is_derived: boolean;
  editable: boolean;
  renamable: boolean;
  deletable: boolean;
  capabilities: string[];
}

export interface RbacConfig {
  capabilities: string[];
  roles: RbacRole[];
}

export interface RoleCreateRequest {
  key: string;
  name: string;
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
  /** Lower/primary grade. -1 = 1. Kindergarten, 0 = 2. Kindergarten, 1..13 = Klassen. */
  jahrgangsstufe: number;
  /** Upper grade for multi-grade classes; null = single grade. */
  jahrgangsstufe_bis: number | null;
  details: string | null;
  status: SchoolClassStatus;
  created_at: string;
  updated_at: string;
}

export interface ClassCreate {
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  jahrgangsstufe_bis?: number | null;
  details?: string | null;
  school_id?: number;
}

export interface ClassUpdate {
  name?: string | null;
  kuerzel?: string | null;
  jahrgangsstufe?: number | null;
  jahrgangsstufe_bis?: number | null;
  details?: string | null;
}

/** Per-school AD provisioning config (target OUs + Zyklus group templates). */
export interface SchoolAdConfig {
  ad_ou_students_zyklus3?: string | null;
  ad_ou_students_other?: string | null;
  ad_ou_teachers?: string | null;
  ad_ou_devices?: string | null;
  ad_ou_company_users?: string | null;
  ad_groups_teacher?: string[] | null;
  ad_groups_student_zyklus1?: string[] | null;
  ad_groups_student_zyklus2?: string[] | null;
  ad_groups_student_zyklus3?: string[] | null;
  ad_groups_company?: string[] | null;
}

export interface SchoolOut {
  id: number;
  name: string;
  kuerzel: string;
  scope_short: string;
  street?: string | null;
  postal_code?: string | null;
  city?: string | null;
  phone?: string | null;
  description?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  // Per-school AD provisioning config (OUs are string|null, groups always arrays).
  ad_ou_students_zyklus3: string | null;
  ad_ou_students_other: string | null;
  ad_ou_teachers: string | null;
  ad_ou_devices: string | null;
  ad_ou_company_users: string | null;
  ad_groups_teacher: string[];
  ad_groups_student_zyklus1: string[];
  ad_groups_student_zyklus2: string[];
  ad_groups_student_zyklus3: string[];
  ad_groups_company: string[];
}

export interface SchoolCreate extends SchoolAdConfig {
  name: string;
  kuerzel: string;
  scope_short: string;
  street?: string | null;
  postal_code?: string | null;
  city?: string | null;
  phone?: string | null;
  description?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

export type SchoolUpdate = Partial<SchoolCreate> & SchoolAdConfig;

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

/** M6: feature modules enabled for this instance (GET /me/modules). */
export interface ModuleOut {
  id: string;
  depends_on: string[];
}

export interface ModulesOut {
  profile: string;
  modules: ModuleOut[];
}

/** M6 Phase 1: admin view + update of the module configuration. */
export interface AdminModuleOut {
  id: string;
  toggleable: boolean;
  enabled: boolean;
  depends_on: string[];
  default_in_profiles: string[];
}

export interface AdminModulesOut {
  instance_profile: string;
  known_profiles: string[];
  modules: AdminModuleOut[];
  module_overrides: Record<string, boolean>;
}

export interface ModuleSettingsUpdate {
  instance_profile?: string;
  module_overrides?: Record<string, boolean>;
}

/** M6 Phase 2: company-edition departments + memberships + manager roles. */
export interface DepartmentOut {
  id: number;
  school_id: number;
  name: string;
  kuerzel: string | null;
  details: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DepartmentCreate {
  name: string;
  kuerzel?: string | null;
  details?: string | null;
  school_id?: number;
}

export interface DepartmentMembershipOut {
  id: number;
  department_id: number;
  ad_object_guid: string;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

export interface ManagerRoleOut {
  id: number;
  department_id: number;
  ad_object_guid: string;
  role: string;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}

// #9: a department a user is an active member of (user-centric assignment view).
export interface UserDepartmentOut {
  membership_id: number;
  department_id: number;
  name: string;
  kuerzel: string | null;
  valid_from: string;
}

export interface ManagerRoleCreate {
  ad_object_guid: string;
  role?: "lead" | "deputy";
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
  jahrgangsstufe: number | null;
}

export interface ClassDeviceOut {
  id: number;
  name: string;
  device_type: string | null;
  serial_number: string | null;
  is_loan: boolean;
  assignee_kind: "student" | "teacher" | "class";
  assignee_label: string;
}

export interface ClassAdvanceRequest {
  student_guids: string[];
  target_class_id?: number | null;
  grade_delta?: number;
  archive_source?: boolean;
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
  jahrgangsstufe_bis?: number | null;
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
  ad_missing_since: string | null;
  street_address: string | null;
  locality: string | null;
  postal_code: string | null;
  country: string | null;
  title: string | null;
  department: string | null;
  company: string | null;
  telephone_number: string | null;
  mobile: string | null;
  office: string | null;
  description: string | null;
  employee_id: string | null;
  device_name: string | null;
  temp_device_name: string | null;
  jahrgangsstufe: number | null;
  /** AD: DONT_EXPIRE_PASSWD (userAccountControl bit). */
  password_never_expires: boolean;
  /** AD: "user cannot change password" (enforced via the object's DACL). */
  cannot_change_password: boolean;
  /** Vault: keep the last set password encrypted in Magister. */
  store_password: boolean;
  /** Synced AD group memberships (memberOf DNs). */
  ad_groups: string[];
  /** Secondary SMTP addresses (aliases) mirrored from proxyAddresses. */
  mail_aliases: string[];
}

export interface UserDeletionImpact {
  class_memberships: number;
  class_teacher_roles: number;
  subject_teacher_roles: number;
  role_assignments: number;
  user_preferences: number;
  sessions: number;
}

/** PATCH /users/{guid} — omit a field to leave it alone. Empty string/null
 *  clears (where the backend allows it). `upn` and `sam_account_name` are
 *  admin-only and must be non-empty when sent. */
export interface UserAttributesUpdate {
  display_name?: string | null;
  given_name?: string | null;
  surname?: string | null;
  upn?: string | null;
  sam_account_name?: string | null;
  mail?: string | null;
  /** Full replacement of the secondary-address list; [] clears all aliases. */
  mail_aliases?: string[] | null;
  street_address?: string | null;
  locality?: string | null;
  postal_code?: string | null;
  country?: string | null;
  title?: string | null;
  department?: string | null;
  company?: string | null;
  telephone_number?: string | null;
  mobile?: string | null;
  office?: string | null;
  description?: string | null;
  employee_id?: string | null;
  temp_device_name?: string | null;
  jahrgangsstufe?: number | null;
  password_never_expires?: boolean | null;
  cannot_change_password?: boolean | null;
  store_password?: boolean | null;
}

/** PATCH /users/{guid}/status — enable/disable an AD account. */
export interface UserStatusUpdate {
  enabled: boolean;
  reason?: string | null;
}

/** POST /users/{guid}/rename/preview — request the cascaded suggestion. */
export interface RenamePreviewRequest {
  new_surname: string;
  new_given_name?: string | null;
}

/** POST /users/{guid}/rename/preview — suggested (editable) values. */
export interface RenamePreviewOut {
  given_name: string | null;
  surname: string;
  display_name: string;
  upn: string | null;
  mail: string | null;
  sam_account_name: string | null;
  old_mail_kept_as_alias: string | null;
}

/** POST /users/{guid}/rename — operator-confirmed final values. */
export interface RenameApplyRequest {
  given_name?: string | null;
  surname?: string | null;
  display_name?: string | null;
  upn?: string | null;
  sam_account_name?: string | null;
  mail?: string | null;
  keep_old_mail_as_alias?: boolean;
}

export interface MailDomainsOut {
  domains: string[];
}

// --- Document templates (M6 Feature B) ---

export interface DocumentTemplateOut {
  id: number;
  key: string;
  language: string;
  school_id: number | null;
  subject: string | null;
  body_html: string;
  is_active: boolean;
  updated_by: string | null;
  updated_at: string;
}

export interface DocumentTemplateMetaOut {
  keys: string[];
  placeholders: string[];
  languages: string[];
  /** Built-in starter content per key — the "template for the template". */
  starters: Record<string, { subject: string; body_html: string }>;
}

export interface DocumentTemplateListOut {
  templates: DocumentTemplateOut[];
  meta: DocumentTemplateMetaOut;
}

export interface DocumentTemplateSave {
  key: string;
  language: string;
  school_id?: number | null;
  subject?: string | null;
  body_html: string;
  is_active?: boolean;
}

export interface DocumentTemplatePreviewRequest {
  body_html: string;
  subject?: string | null;
}

export interface DocumentTemplatePreviewOut {
  subject: string | null;
  html: string;
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
  password_store_enabled: boolean;
  ad_groups_search_base: string | null;
  ad_groups_teacher: string[];
  ad_groups_student_zyklus1: string[];
  ad_groups_student_zyklus2: string[];
  ad_groups_student_zyklus3: string[];
  web_tls_cert_set: boolean;
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
  device_count: number;
  group_count: number;
}

export type AdUserOuKey =
  | "teacher"
  | "student_zyklus1"
  | "student_zyklus2"
  | "student_zyklus3"
  | "company";

export interface AdUserCreateRequest {
  given_name: string;
  surname: string;
  sam_account_name: string;
  user_principal_name: string;
  mail?: string | null;
  ou_key: AdUserOuKey;
  school_id: number;
  display_name?: string | null;
  force_change?: boolean;
  cannot_change_password?: boolean;
  password_never_expires?: boolean;
  jahrgangsstufe?: number | null;
}

export interface AdGroupOut {
  ad_object_guid: string;
  distinguished_name: string;
  cn: string;
  sam_account_name: string | null;
  description: string | null;
}

export interface UserGroupsUpdate {
  groups: string[];
}

export interface UserGroupsResult {
  added: string[];
  removed: string[];
  failed: string[];
  groups: string[];
}

export interface AdUserCreateResponse {
  ad_object_guid: string;
  temp_password: string;
  force_change: boolean;
}

export interface AdUserDeleteResponse {
  ad_object_guid: string;
  ad_removed: boolean;
}

export interface DemoPurgeResponse {
  found: boolean;
  schools: number;
  classes: number;
  users: number;
}

export interface AuditResetResponse {
  deleted: number;
  imports_deleted: number;
}

export interface SystemCommandResult {
  action: string | null;
  state: string | null;
  message: string | null;
  git_sha: string | null;
  started_at: string | null;
  finished_at: string | null;
}
export interface SystemStatusOut {
  configured: boolean;
  pending: number;
  last: SystemCommandResult | null;
  log: string | null;
}
export interface SystemCommandResponse {
  id: string;
  action: string;
  requested_at: string;
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
  /** Advance each moved student's grade by +1 (default true). */
  bump_grade?: boolean;
  /** ad_object_guid -> explicit new grade (exceptions: stay/skip). */
  grade_overrides?: Record<string, number> | null;
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

// --- Devices ---------------------------------------------------------------

/** Device inventory row. Managed in Magister; imported from AD by name only. */
export interface DeviceOut {
  id: number;
  name: string;
  device_type: string | null;
  serial_number: string | null;
  notes: string | null;
  school_id: number | null;
  class_id: number | null;
  assigned_person_guid: string | null;
  assigned_person_name: string | null;
  is_loan: boolean;
  ad_object_guid: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface DeviceCreate {
  name: string;
  device_type?: string | null;
  serial_number?: string | null;
  notes?: string | null;
}

export interface DeviceUpdate {
  name?: string | null;
  device_type?: string | null;
  serial_number?: string | null;
  notes?: string | null;
}

export type DeviceAssignmentType = "person" | "class" | "school" | "free";

export interface DeviceAssign {
  assignment_type: DeviceAssignmentType;
  person_guid?: string | null;
  class_id?: number | null;
  school_id?: number | null;
  is_loan?: boolean;
}

export interface DeviceAssignmentOut {
  id: number;
  assignment_type: "person" | "class" | "school";
  label: string;
  is_loan: boolean;
  valid_from: string;
  valid_to: string | null;
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
  jahrgangsstufe_bis?: number | null;
  student_count: number;
}
export interface StudentsByClassReport {
  rows: StudentsByClassRow[];
  total_students: number;
  total_classes: number;
}

export interface StudentsBySchoolYearRow {
  jahrgangsstufe: number | null;
  student_count: number;
}
export interface StudentsBySchoolYearReport {
  rows: StudentsBySchoolYearRow[];
  total_students: number;
}

export interface TeacherWorkloadRow {
  ad_object_guid: string;
  upn: string | null;
  display_name: string | null;
  haupt_count: number;
  co_count: number;
  stellvertretung_count: number;
  total: number;
  classes: string[];
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

// Company edition (M6 #8): department-centric reports.
export interface MembersByDepartmentRow {
  department_id: number;
  school_id: number;
  name: string;
  kuerzel: string | null;
  member_count: number;
  lead_count: number;
}
export interface MembersByDepartmentReport {
  rows: MembersByDepartmentRow[];
  total_members: number;
  total_departments: number;
}

export interface ManagerWorkloadRow {
  ad_object_guid: string;
  upn: string | null;
  display_name: string | null;
  lead_count: number;
  deputy_count: number;
  total: number;
  departments: string[];
}
export interface ManagerWorkloadReport {
  rows: ManagerWorkloadRow[];
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

export type ImportKind =
  | "classes"
  | "class_memberships"
  | "class_teachers"
  | "students"
  | "teachers"
  | "company_users";
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
  sam_account_name: string;
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
  password_store_enabled?: boolean | null;
  ad_groups_search_base?: string | null;
  ad_groups_teacher?: string[] | null;
  ad_groups_student_zyklus1?: string[] | null;
  ad_groups_student_zyklus2?: string[] | null;
  ad_groups_student_zyklus3?: string[] | null;
  web_tls_cert_pem?: string | null;
  web_tls_key_pem?: string | null;
  web_tls_pfx_base64?: string | null;
  web_tls_pfx_password?: string | null;
}
