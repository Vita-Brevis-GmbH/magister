/** React-Query hooks per backend resource. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { AdUserListResponse, ClassOut, CurrentUserOut } from "./types";

export const queryKeys = {
  me: ["me"] as const,
  classes: ["classes"] as const,
  users: (params: UseUsersParams) => ["users", params] as const,
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
