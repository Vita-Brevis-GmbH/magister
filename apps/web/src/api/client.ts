/**
 * Thin fetch wrapper that:
 * - reads the `magister_csrf` cookie and mirrors it into `X-CSRF-Token`
 *   on mutating requests (CSRF double-submit; see backend csrf.py).
 * - throws a typed {@link ApiError} on non-2xx so React-Query's onError
 *   layer can handle it once.
 * - on 401, clears query cache and redirects to /login (where the user
 *   can hit a full-page link to /api/auth/login for the OIDC redirect).
 *
 * All paths passed in are relative to the API root and are prefixed with
 * {@link API_BASE} ("/api"). Caddy's `handle_path /api/*` strips the prefix
 * before forwarding to the backend, which still mounts at "/".
 */

import type { QueryClient } from "@tanstack/react-query";

export const API_BASE = "/api";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const CSRF_COOKIE = "magister_csrf";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly bodyText: string,
  ) {
    super(`${status} ${code}`);
    this.name = "ApiError";
  }
}

let queryClient: QueryClient | null = null;
export function bindQueryClient(qc: QueryClient): void {
  queryClient = qc;
}

function readCsrfCookie(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]+)`));
  return match ? decodeURIComponent(match[1]!) : null;
}

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  body?: unknown;
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCsrfCookie();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  let body: BodyInit | undefined;
  if (init.body !== undefined && init.body !== null) {
    if (init.body instanceof FormData || init.body instanceof URLSearchParams) {
      body = init.body;
    } else {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(init.body);
    }
  }

  const url = path.startsWith("/") ? `${API_BASE}${path}` : path;
  const res = await fetch(url, {
    ...init,
    method,
    headers,
    body,
    credentials: "include",
  });

  if (res.status === 401) {
    queryClient?.clear();
    if (window.location.pathname !== "/login") {
      window.location.assign("/login");
    }
    throw new ApiError(401, "unauthenticated", "");
  }

  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");

  if (!res.ok) {
    let code = res.statusText || "error";
    let bodyText = "";
    if (isJson) {
      try {
        const j = (await res.json()) as { detail?: unknown };
        if (typeof j.detail === "string") code = j.detail;
        bodyText = JSON.stringify(j);
      } catch {
        // fall through; bodyText stays empty
      }
    } else {
      bodyText = await res.text();
    }
    throw new ApiError(res.status, code, bodyText);
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  if (isJson) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}
