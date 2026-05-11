/** React-Query hooks per backend resource. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type ApiError } from "./client";
import type {
  AdUserListResponse,
  AppSettingsOut,
  AppSettingsUpdate,
  AuthCapabilities,
  ClassOut,
  CurrentUserOut,
  LocalAdminOut,
  LocalAdminPasswordChangeRequest,
  LocalLoginRequest,
  StudentPasswordResetRequest,
  StudentPasswordResetResponse,
} from "./types";

export const queryKeys = {
  me: ["me"] as const,
  classes: ["classes"] as const,
  users: (params: UseUsersParams) => ["users", params] as const,
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
