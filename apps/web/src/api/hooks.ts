/** React-Query hooks per backend resource. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, ApiError, apiFetch } from "./client";
import type {
  AdConnectionTestOut,
  AdLoginRequest,
  AdSyncResultOut,
  AdUserCreateRequest,
  AdUserCreateResponse,
  AdUserDeleteResponse,
  AdUserListResponse,
  AdUserOut,
  DemoPurgeResponse,
  AppSettingsOut,
  AppSettingsUpdate,
  AuditEventListResponse,
  AuthCapabilities,
  BulkClassMembershipCreate,
  BulkClassMembershipResult,
  ClassCreate,
  ClassMembershipCreate,
  ClassMembershipOut,
  ClassOut,
  ClassPromotionRequest,
  ClassPromotionResult,
  DeviceOut,
  DeviceCreate,
  DeviceUpdate,
  DeviceAssign,
  ClassTeacherCreate,
  ClassTeacherOut,
  ClassUpdate,
  MyStudentsOut,
  SubjectTeacherCreate,
  SubjectTeacherOut,
  CurrentUserOut,
  ActivityReport,
  ImportApplyResult,
  ImportJobDetailOut,
  ImportJobOut,
  ImportKind,
  ProvisionedCredential,
  LetterRequest,
  LetterTemplate,
  StudentsByClassReport,
  SubjectAccessReport,
  TeacherWorkloadReport,
  LocalAdminOut,
  LocalAdminPasswordChangeRequest,
  LocalLoginRequest,
  RoleAssignmentOut,
  RoleGrantRequest,
  MailDomainsOut,
  SchoolOut,
  SchoolCreate,
  SchoolUpdate,
  StudentPasswordResetRequest,
  StudentPasswordResetResponse,
  SubstitutionOut,
  UserAttributesUpdate,
  UserDashboardOut,
  UserPreferencesOut,
  UserPreferencesUpdate,
  UserStatusUpdate,
} from "./types";

export const queryKeys = {
  me: ["me"] as const,
  classes: ["classes"] as const,
  schools: ["schools"] as const,
  classDetail: (classId: number) => ["classes", classId] as const,
  classTeachers: (classId: number) => ["classes", classId, "teachers"] as const,
  subjectTeachers: (classId: number) => ["classes", classId, "subject-teachers"] as const,
  myStudents: ["me", "students"] as const,
  classMemberships: (classId: number) => ["classes", classId, "students"] as const,
  users: (params: UseUsersParams) => ["users", params] as const,
  user: (guid: string) => ["user", guid] as const,
  userDashboard: (guid: string) => ["user", guid, "dashboard"] as const,
  mailDomains: ["mail-domains"] as const,
  authCapabilities: ["auth-capabilities"] as const,
  localAdmin: ["local-admin"] as const,
  appSettings: ["app-settings"] as const,
  myPreferences: ["me", "preferences"] as const,
  auditEvents: (params: UseAuditEventsParams) => ["audit-events", params] as const,
  roles: ["admin-roles"] as const,
  devices: ["devices"] as const,
};

// --- Current user ----------------------------------------------------------

export function useCurrentUser(opts: { retryOn401?: boolean } = {}) {
  return useQuery<CurrentUserOut>({
    queryKey: queryKeys.me,
    queryFn: () => apiFetch<CurrentUserOut>("/auth/me"),
    retry: opts.retryOn401 ? 2 : false,
    staleTime: 5 * 60_000,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ ok: true }>("/auth/logout", { method: "POST" }),
    // Land on /login whether or not the server call succeeded, so the button
    // never appears to "do nothing" — the session is cleared server-side on
    // success, and on any failure the login screen re-evaluates the session.
    onSettled: () => {
      qc.clear();
      window.location.assign("/login");
    },
  });
}

// --- Classes ---------------------------------------------------------------

export function useClasses() {
  return useQuery<ClassOut[]>({
    queryKey: queryKeys.classes,
    queryFn: () => apiFetch<ClassOut[]>("/classes"),
  });
}

export function useSchools() {
  return useQuery<SchoolOut[]>({
    queryKey: queryKeys.schools,
    queryFn: () => apiFetch<SchoolOut[]>("/schools"),
    staleTime: 5 * 60_000,
  });
}

export function useCreateSchool() {
  const qc = useQueryClient();
  return useMutation<SchoolOut, ApiError, SchoolCreate>({
    mutationFn: (body) => apiFetch<SchoolOut>("/schools", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schools });
    },
  });
}

export function useUpdateSchool(schoolId: number) {
  const qc = useQueryClient();
  return useMutation<SchoolOut, ApiError, SchoolUpdate>({
    mutationFn: (body) => apiFetch<SchoolOut>(`/schools/${schoolId}`, { method: "PATCH", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schools });
    },
  });
}

export function useDeleteSchool() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (schoolId) => apiFetch<void>(`/schools/${schoolId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schools });
    },
  });
}

export function useClass(classId: number) {
  return useQuery<ClassOut>({
    queryKey: queryKeys.classDetail(classId),
    queryFn: () => apiFetch<ClassOut>(`/classes/${classId}`),
  });
}

export function useCreateClass() {
  const qc = useQueryClient();
  return useMutation<ClassOut, ApiError, ClassCreate>({
    mutationFn: (body) => apiFetch<ClassOut>("/classes", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

export function useUpdateClass(classId: number) {
  const qc = useQueryClient();
  return useMutation<ClassOut, ApiError, ClassUpdate>({
    mutationFn: (body) => apiFetch<ClassOut>(`/classes/${classId}`, { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.classDetail(classId), data);
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

export function useArchiveClass() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (classId) => apiFetch<void>(`/classes/${classId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

// --- Devices ---------------------------------------------------------------

export function useDevices() {
  return useQuery<DeviceOut[]>({
    queryKey: queryKeys.devices,
    queryFn: () => apiFetch<DeviceOut[]>("/devices"),
  });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation<DeviceOut, ApiError, DeviceCreate>({
    mutationFn: (body) => apiFetch<DeviceOut>("/devices", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.devices });
    },
  });
}

export function useUpdateDevice(deviceId: number) {
  const qc = useQueryClient();
  return useMutation<DeviceOut, ApiError, DeviceUpdate>({
    mutationFn: (body) => apiFetch<DeviceOut>(`/devices/${deviceId}`, { method: "PATCH", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.devices });
    },
  });
}

export function useAssignDevice(deviceId: number) {
  const qc = useQueryClient();
  return useMutation<DeviceOut, ApiError, DeviceAssign>({
    mutationFn: (body) =>
      apiFetch<DeviceOut>(`/devices/${deviceId}/assign`, { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.devices });
    },
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (deviceId) => apiFetch<void>(`/devices/${deviceId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.devices });
    },
  });
}

// --- Class teachers --------------------------------------------------------

export function useClassTeachers(classId: number) {
  return useQuery<ClassTeacherOut[]>({
    queryKey: queryKeys.classTeachers(classId),
    queryFn: () => apiFetch<ClassTeacherOut[]>(`/classes/${classId}/teachers`),
  });
}

export function useAssignClassTeacher(classId: number) {
  const qc = useQueryClient();
  return useMutation<ClassTeacherOut, ApiError, ClassTeacherCreate>({
    mutationFn: (body) =>
      apiFetch<ClassTeacherOut>(`/classes/${classId}/teachers`, {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classTeachers(classId) });
    },
  });
}

export function useRevokeClassTeacher(classId: number) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (roleId) =>
      apiFetch<void>(`/classes/${classId}/teachers/${roleId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classTeachers(classId) });
    },
  });
}

// --- Subject teachers (Fachlehrer) -----------------------------------------

export function useSubjectTeachers(classId: number) {
  return useQuery<SubjectTeacherOut[]>({
    queryKey: queryKeys.subjectTeachers(classId),
    queryFn: () => apiFetch<SubjectTeacherOut[]>(`/classes/${classId}/subject-teachers`),
  });
}

export function useAssignSubjectTeacher(classId: number) {
  const qc = useQueryClient();
  return useMutation<SubjectTeacherOut, ApiError, SubjectTeacherCreate>({
    mutationFn: (body) =>
      apiFetch<SubjectTeacherOut>(`/classes/${classId}/subject-teachers`, {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.subjectTeachers(classId) });
    },
  });
}

export function useRevokeSubjectTeacher(classId: number) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (roleId) =>
      apiFetch<void>(`/classes/${classId}/subject-teachers/${roleId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.subjectTeachers(classId) });
    },
  });
}

export function useMyStudents() {
  return useQuery<MyStudentsOut>({
    queryKey: queryKeys.myStudents,
    queryFn: () => apiFetch<MyStudentsOut>("/me/students"),
  });
}

// --- Class memberships -----------------------------------------------------

export function useClassMemberships(classId: number) {
  return useQuery<ClassMembershipOut[]>({
    queryKey: queryKeys.classMemberships(classId),
    queryFn: () => apiFetch<ClassMembershipOut[]>(`/classes/${classId}/students`),
  });
}

export function useAddClassMembership(classId: number) {
  const qc = useQueryClient();
  return useMutation<ClassMembershipOut, ApiError, ClassMembershipCreate>({
    mutationFn: (body) =>
      apiFetch<ClassMembershipOut>(`/classes/${classId}/students`, {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classMemberships(classId) });
    },
  });
}

export function useRemoveClassMembership(classId: number) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (membershipId) =>
      apiFetch<void>(`/classes/${classId}/students/${membershipId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classMemberships(classId) });
    },
  });
}

export function useBulkAddClassMemberships(classId: number) {
  const qc = useQueryClient();
  return useMutation<BulkClassMembershipResult, ApiError, BulkClassMembershipCreate>({
    mutationFn: (body) =>
      apiFetch<BulkClassMembershipResult>(`/classes/${classId}/students/bulk`, {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classMemberships(classId) });
    },
  });
}

export const substitutionsKey = ["substitutions"] as const;

export function useSubstitutions() {
  return useQuery<SubstitutionOut[]>({
    queryKey: substitutionsKey,
    queryFn: () => apiFetch<SubstitutionOut[]>("/substitutions"),
  });
}

export function useRevokeSubstitution() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (roleId) => apiFetch<void>(`/substitutions/${roleId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: substitutionsKey });
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

export function usePromoteClass(classId: number) {
  const qc = useQueryClient();
  return useMutation<ClassPromotionResult, ApiError, ClassPromotionRequest>({
    mutationFn: (body) =>
      apiFetch<ClassPromotionResult>(`/classes/${classId}/promote`, { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

// --- AD users --------------------------------------------------------------

export interface UseUsersParams {
  kind?: "teacher" | "student" | "admin";
  enabled?: boolean;
  search?: string;
  class_id?: number;
  offset?: number;
  limit?: number;
}

export function useUsers(params: UseUsersParams = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const path = qs.toString() ? `/users?${qs.toString()}` : "/users";
  return useQuery<AdUserListResponse>({
    queryKey: queryKeys.users(params),
    queryFn: () => apiFetch<AdUserListResponse>(path),
  });
}

export function useUser(guid: string) {
  return useQuery<AdUserOut>({
    queryKey: queryKeys.user(guid),
    queryFn: () => apiFetch<AdUserOut>(`/users/${guid}`),
    enabled: !!guid,
  });
}

export function useUserDashboard(guid: string) {
  return useQuery<UserDashboardOut>({
    queryKey: queryKeys.userDashboard(guid),
    queryFn: () => apiFetch<UserDashboardOut>(`/users/${guid}/dashboard`),
    enabled: !!guid,
  });
}

export function useUpdateUser(guid: string) {
  const qc = useQueryClient();
  return useMutation<AdUserOut, ApiError, UserAttributesUpdate>({
    mutationFn: (body) => apiFetch<AdUserOut>(`/users/${guid}`, { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.user(guid), data);
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

/** PATCH /users/{guid}/status — enable or disable an AD account (M2 US-6). */
export function useSetUserStatus(guid: string) {
  const qc = useQueryClient();
  return useMutation<AdUserOut, ApiError, UserStatusUpdate>({
    mutationFn: (body) => apiFetch<AdUserOut>(`/users/${guid}/status`, { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.user(guid), data);
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useMailDomains() {
  return useQuery<MailDomainsOut>({
    queryKey: queryKeys.mailDomains,
    queryFn: () => apiFetch<MailDomainsOut>("/users/mail-domains"),
    staleTime: 5 * 60_000,
  });
}

// --- Auth capabilities + local login --------------------------------------

export function useAuthCapabilities() {
  return useQuery<AuthCapabilities>({
    queryKey: queryKeys.authCapabilities,
    queryFn: () => apiFetch<AuthCapabilities>("/auth/capabilities"),
    // Pre-login screen — keep it cheap; one fetch per page load is enough.
    staleTime: 60_000,
  });
}

export function useLocalLogin() {
  return useMutation<void, ApiError, LocalLoginRequest>({
    mutationFn: (body) =>
      apiFetch<void>("/auth/login/local", {
        method: "POST",
        body,
      }),
  });
}

export function useAdLogin() {
  return useMutation<void, ApiError, AdLoginRequest>({
    mutationFn: (body) =>
      apiFetch<void>("/auth/login/ad", {
        method: "POST",
        body,
      }),
  });
}

// --- Role assignments (admin) ----------------------------------------------

export function useRoles() {
  return useQuery<RoleAssignmentOut[]>({
    queryKey: queryKeys.roles,
    queryFn: () => apiFetch<RoleAssignmentOut[]>("/admin/roles"),
  });
}

export function useGrantRole() {
  const qc = useQueryClient();
  return useMutation<RoleAssignmentOut, ApiError, { guid: string; body: RoleGrantRequest }>({
    mutationFn: ({ guid, body }) =>
      apiFetch<RoleAssignmentOut>(`/admin/users/${encodeURIComponent(guid)}/roles`, {
        method: "POST",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.roles }),
  });
}

export function useRevokeRole() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { guid: string; role: string; school_id: number | null }>({
    mutationFn: ({ guid, role, school_id }) => {
      const params = new URLSearchParams({ role });
      if (school_id != null) params.set("school_id", String(school_id));
      return apiFetch<void>(`/admin/users/${encodeURIComponent(guid)}/roles?${params.toString()}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.roles }),
  });
}

// --- Local admin lifecycle (admin-only) -----------------------------------

export function useLocalAdmin() {
  return useQuery<LocalAdminOut>({
    queryKey: queryKeys.localAdmin,
    queryFn: () => apiFetch<LocalAdminOut>("/admin/local-admin"),
  });
}

export function useChangeLocalAdminPassword() {
  return useMutation<void, ApiError, LocalAdminPasswordChangeRequest>({
    mutationFn: (body) => apiFetch<void>("/admin/local-admin/password", { method: "POST", body }),
  });
}

export function useSetLocalAdminEnabled() {
  const qc = useQueryClient();
  return useMutation<LocalAdminOut, ApiError, boolean>({
    mutationFn: (enabled) =>
      apiFetch<LocalAdminOut>("/admin/local-admin", {
        method: "PATCH",
        body: { enabled },
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.localAdmin, data);
    },
  });
}

// --- App settings (admin-only) --------------------------------------------

export function useAppSettings() {
  return useQuery<AppSettingsOut>({
    queryKey: queryKeys.appSettings,
    queryFn: () => apiFetch<AppSettingsOut>("/admin/app-settings"),
  });
}

export function useUpdateAppSettings() {
  const qc = useQueryClient();
  return useMutation<AppSettingsOut, ApiError, AppSettingsUpdate>({
    mutationFn: (body) => apiFetch<AppSettingsOut>("/admin/app-settings", { method: "PUT", body }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.appSettings, data);
      // Capabilities may flip when oidc_issuer/client_id change.
      qc.invalidateQueries({ queryKey: queryKeys.authCapabilities });
    },
  });
}

export function useTestAdConnection() {
  return useMutation<AdConnectionTestOut, ApiError, void>({
    mutationFn: () => apiFetch<AdConnectionTestOut>("/admin/ad-test", { method: "POST" }),
  });
}

export function useCreateAdUser() {
  const qc = useQueryClient();
  return useMutation<AdUserCreateResponse, ApiError, AdUserCreateRequest>({
    mutationFn: (body) =>
      apiFetch<AdUserCreateResponse>("/admin/ad-users", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDeleteAdUser() {
  const qc = useQueryClient();
  return useMutation<AdUserDeleteResponse, ApiError, string>({
    mutationFn: (guid) =>
      apiFetch<AdUserDeleteResponse>(`/admin/ad-users/${encodeURIComponent(guid)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: queryKeys.roles });
    },
  });
}

export function usePurgeDemoData() {
  const qc = useQueryClient();
  return useMutation<DemoPurgeResponse, ApiError, void>({
    mutationFn: () => apiFetch<DemoPurgeResponse>("/admin/demo-data/purge", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: queryKeys.classes });
      qc.invalidateQueries({ queryKey: queryKeys.schools });
    },
  });
}

export function useTriggerAdSync() {
  const qc = useQueryClient();
  return useMutation<AdSyncResultOut, ApiError, void>({
    mutationFn: () => apiFetch<AdSyncResultOut>("/admin/ad-sync?mode=full", { method: "POST" }),
    onSuccess: () => {
      // Fresh rows + updated last_sync_at.
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: queryKeys.appSettings });
    },
  });
}

// --- Per-user preferences --------------------------------------------------

export function useMyPreferences() {
  return useQuery<UserPreferencesOut>({
    queryKey: queryKeys.myPreferences,
    queryFn: () => apiFetch<UserPreferencesOut>("/me/preferences"),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateMyPreferences() {
  const qc = useQueryClient();
  return useMutation<UserPreferencesOut, ApiError, UserPreferencesUpdate>({
    mutationFn: (body) => apiFetch<UserPreferencesOut>("/me/preferences", { method: "PUT", body }),
    onSuccess: (data) => qc.setQueryData(queryKeys.myPreferences, data),
  });
}

// --- Student password reset ------------------------------------------------

export function useResetStudentPassword(adObjectGuid: string) {
  return useMutation<StudentPasswordResetResponse, ApiError, StudentPasswordResetRequest>({
    mutationFn: (body) =>
      apiFetch<StudentPasswordResetResponse>(`/students/${adObjectGuid}/password-reset`, {
        method: "POST",
        body,
      }),
  });
}

// Same request/response shape as the student endpoint (teacher schemas
// subclass them); gated to admin / SMI-of-the-teacher's-school on the backend.
export function useResetTeacherPassword(adObjectGuid: string) {
  return useMutation<StudentPasswordResetResponse, ApiError, StudentPasswordResetRequest>({
    mutationFn: (body) =>
      apiFetch<StudentPasswordResetResponse>(`/teachers/${adObjectGuid}/password-reset`, {
        method: "POST",
        body,
      }),
  });
}

// --- Audit events (M2 US-7) -----------------------------------------------

export interface UseAuditEventsParams {
  action?: string;
  target_kind?: string;
  target_id?: string;
  actor_upn?: string;
  from_ts?: string;
  to_ts?: string;
  school_id?: number;
  offset?: number;
  limit?: number;
}

export function useAuditEvents(params: UseAuditEventsParams = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const path = qs.toString() ? `/audit/events?${qs.toString()}` : "/audit/events";
  return useQuery<AuditEventListResponse>({
    queryKey: queryKeys.auditEvents(params),
    queryFn: () => apiFetch<AuditEventListResponse>(path),
  });
}

// --- CSV imports (M3 US-2) -------------------------------------------------

export const importsKey = ["imports"] as const;

export function useImportJobs() {
  return useQuery<ImportJobOut[]>({
    queryKey: importsKey,
    queryFn: () => apiFetch<ImportJobOut[]>("/imports"),
  });
}

export function useImportJob(jobId: number | null) {
  return useQuery<ImportJobDetailOut>({
    queryKey: ["imports", jobId],
    queryFn: () => apiFetch<ImportJobDetailOut>(`/imports/${jobId}`),
    enabled: jobId !== null,
  });
}

export function useStageImport() {
  const qc = useQueryClient();
  return useMutation<
    ImportJobDetailOut,
    ApiError,
    { kind: ImportKind; file: File; schoolId?: number }
  >({
    mutationFn: async ({ kind, file, schoolId }) => {
      const form = new FormData();
      form.append("file", file);
      const qs = new URLSearchParams({ kind });
      if (schoolId !== undefined) qs.set("school_id", String(schoolId));
      return apiFetch<ImportJobDetailOut>(`/imports?${qs.toString()}`, {
        method: "POST",
        body: form,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: importsKey });
    },
  });
}

export function useApplyImport() {
  const qc = useQueryClient();
  return useMutation<ImportApplyResult, ApiError, number>({
    mutationFn: (jobId) =>
      apiFetch<ImportApplyResult>(`/imports/${jobId}/apply`, { method: "POST" }),
    onSuccess: (_data, jobId) => {
      qc.invalidateQueries({ queryKey: importsKey });
      qc.invalidateQueries({ queryKey: ["imports", jobId] });
      qc.invalidateQueries({ queryKey: queryKeys.classes });
    },
  });
}

/**
 * POST the one-time credentials to the stateless PDF renderer and trigger a
 * browser download of the ZIP (per-student hand-outs + per-class table).
 * Credentials are never persisted; this re-sends them over the same session.
 */
export async function downloadHandouts(
  credentials: ProvisionedCredential[],
  schoolName: string,
  language = "de",
): Promise<void> {
  const csrf = document.cookie.match(/(?:^|; )magister_csrf=([^;]+)/)?.[1];
  const res = await fetch(`${API_BASE}/imports/handouts`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
    },
    body: JSON.stringify({ credentials, school_name: schoolName, language }),
  });
  if (!res.ok) throw new ApiError(res.status, "handout_render_failed", await res.text());
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "schueler-zugangsdaten.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function useCancelImport() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, number>({
    mutationFn: (jobId) => apiFetch<void>(`/imports/${jobId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: importsKey });
    },
  });
}

// --- Letters (M3 US-1): server returns a PDF stream ------------------------

export async function downloadLetter(
  template: LetterTemplate,
  body: LetterRequest,
): Promise<{ blob: Blob; filename: string }> {
  const csrf = document.cookie
    .split("; ")
    .find((c) => c.startsWith("magister_csrf="))
    ?.slice("magister_csrf=".length);
  const res = await fetch(`${API_BASE}/letters/${template}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/pdf",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j.detail || j.code || "";
    } catch {
      /* leave empty */
    }
    throw new ApiError(res.status, detail || String(res.status), "");
  }
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  return { blob, filename: match?.[1] ?? `${template}.pdf` };
}

export async function downloadCredentialPdf(
  guid: string,
  body: { custom_heading?: string | null; custom_body?: string | null; language?: string },
): Promise<{ blob: Blob; filename: string }> {
  const csrf = document.cookie
    .split("; ")
    .find((c) => c.startsWith("magister_csrf="))
    ?.slice("magister_csrf=".length);
  const res = await fetch(`${API_BASE}/users/${guid}/credential-pdf`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/pdf",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j.detail || j.code || "";
    } catch {
      /* leave empty */
    }
    throw new ApiError(res.status, detail || String(res.status), "");
  }
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  return { blob, filename: match?.[1] ?? `zugangsdaten-${guid}.pdf` };
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- Reports (M3 US-3) -----------------------------------------------------

export function useStudentsByClass() {
  return useQuery<StudentsByClassReport>({
    queryKey: ["reports", "students-by-class"],
    queryFn: () => apiFetch<StudentsByClassReport>("/reports/students-by-class"),
  });
}

export function useTeacherWorkload() {
  return useQuery<TeacherWorkloadReport>({
    queryKey: ["reports", "teacher-workload"],
    queryFn: () => apiFetch<TeacherWorkloadReport>("/reports/teacher-workload"),
  });
}

export function useActivityReport(days: number = 30) {
  return useQuery<ActivityReport>({
    queryKey: ["reports", "activity", days],
    queryFn: () => apiFetch<ActivityReport>(`/reports/activity?days=${days}`),
  });
}

// --- Privacy / subject-access (M3 US-4 + US-5) -----------------------------

export function useSubjectAccess(guid: string | null) {
  return useQuery<SubjectAccessReport>({
    queryKey: ["privacy", "subject-access", guid],
    queryFn: () => apiFetch<SubjectAccessReport>(`/privacy/subject-access/${guid}`),
    enabled: !!guid,
  });
}

export function subjectAccessCsvUrl(guid: string): string {
  return `${API_BASE}/privacy/subject-access/${guid}/export.csv`;
}
