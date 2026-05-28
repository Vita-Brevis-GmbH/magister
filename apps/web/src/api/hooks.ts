/** React-Query hooks per backend resource. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type ApiError } from "./client";
import type {
  AdUserListResponse,
  AdUserOut,
  AppSettingsOut,
  AppSettingsUpdate,
  AuthCapabilities,
  ClassCreate,
  ClassMembershipCreate,
  ClassMembershipOut,
  ClassOut,
  ClassTeacherCreate,
  ClassTeacherOut,
  ClassUpdate,
  CurrentUserOut,
  LocalAdminOut,
  LocalAdminPasswordChangeRequest,
  LocalLoginRequest,
  MailDomainsOut,
  StudentPasswordResetRequest,
  StudentPasswordResetResponse,
  UserAttributesUpdate,
  UserStatusUpdate,
} from "./types";

export const queryKeys = {
  me: ["me"] as const,
  classes: ["classes"] as const,
  classDetail: (classId: number) => ["classes", classId] as const,
  classTeachers: (classId: number) => ["classes", classId, "teachers"] as const,
  classMemberships: (classId: number) => ["classes", classId, "students"] as const,
  users: (params: UseUsersParams) => ["users", params] as const,
  user: (guid: string) => ["user", guid] as const,
  mailDomains: ["mail-domains"] as const,
  authCapabilities: ["auth-capabilities"] as const,
  localAdmin: ["local-admin"] as const,
  appSettings: ["app-settings"] as const,
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
    onSuccess: () => {
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
