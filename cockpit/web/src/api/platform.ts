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

/** Ein Eintrag im Zustandsbericht des Hosts: jeder hat `ok`, der Rest je Art. */
export interface HealthItem {
  ok: boolean;
  [key: string]: unknown;
}

/** Zustand des Plattform-Hosts, erhoben vom Ops-Agenten (scripts/plattform_zustand.py). */
export interface PlatformHealth {
  configured: boolean;
  present: boolean;
  age_seconds: number | null;
  stale: boolean;
  error: string | null;
  report: {
    ok: boolean;
    generated_at: string;
    host: string;
    services: HealthItem[];
    ports: HealthItem[];
    probes: HealthItem[];
    certificates: HealthItem[];
    disk: HealthItem[];
  } | null;
}

export const getPlatformHealth = () => get<PlatformHealth>("/api/platform/ops/health");
