import { get, post } from "./client";

/** Neustart und Update der ganzen Plattform (ADR-0024 D5). */
export interface OpsStatus {
  configured: boolean;
  pending: number;
  last: {
    action?: string;
    state?: string;
    message?: string;
    git_sha?: string;
    started_at?: string;
    finished_at?: string;
    requested_by?: string;
    /** Nur beim Anbinden: welcher Kunde. */
    slug?: string;
  } | null;
  log: string | null;
}

export const getOpsStatus = () => get<OpsStatus>("/api/platform/ops");

export const requestOps = (action: "restart" | "update") =>
  post<{ id: string; action: string; requested_at: string }>(`/api/platform/ops/${action}`);

/** Einen Kunden auf der Datenebene anbinden lassen (DSN und Schlüssel nachtragen). */
export const requestAttach = (tenantId: string) =>
  post<{ id: string; action: string; requested_at: string; slug: string }>(
    `/api/tenants/${tenantId}/attach`,
  );
