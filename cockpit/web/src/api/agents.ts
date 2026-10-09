import { get, post, put } from "./client";

export type AgentStatus = "enrolled" | "online" | "stale" | "revoked";
export type JobState = "queued" | "claimed" | "done" | "failed" | "expired";

export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  status: AgentStatus;
  certificate_serial: string;
  certificate_not_after: string;
  spki_sha256: string;
  /** Während des Erneuerungsfensters gelten beide Fingerprints (ADR-0014). */
  previous_spki_sha256: string | null;
  spki_rotated_at: string | null;
  agent_version: string | null;
  last_seen_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  created_at: string;
}

/**
 * Ein Einmal-Token für die Anmeldung eines Agenten.
 *
 * `token` kommt **genau einmal** und lebt 24 Stunden. Es gilt einmal — wer
 * sich damit anmeldet, ist der Agent. Deshalb gehört es nicht in eine
 * E-Mail und nicht in ein Ticket.
 */
export interface Enrollment {
  id: string;
  agent_name: string;
  expires_at: string;
  token: string;
  /** Für `enroll --endpoint`; leer, wenn die Konsole ihren Connector-Namen nicht kennt. */
  endpoint: string;
}

export interface ConnectorJob {
  id: string;
  tenant_id: string;
  agent_id: string | null;
  method: string;
  state: JobState;
  error: string | null;
  payload_purged_at: string | null;
  expires_at: string;
  claimed_at: string | null;
  finished_at: string | null;
  attempts: number;
  created_at: string;
}

export function listAgents(tenantId: string): Promise<Agent[]> {
  return get(`/api/tenants/${tenantId}/agents`);
}

export function createEnrollment(tenantId: string, agentName: string): Promise<Enrollment> {
  return post(`/api/tenants/${tenantId}/enrollments`, { agent_name: agentName });
}

export function revokeAgent(tenantId: string, agentId: string, reason: string): Promise<Agent> {
  return post(`/api/tenants/${tenantId}/agents/${agentId}/revoke`, { reason });
}

export function listConnectorJobs(tenantId: string): Promise<ConnectorJob[]> {
  return get(`/api/tenants/${tenantId}/jobs`);
}

/** Tage bis zum Ablauf des Zertifikats; negativ heisst abgelaufen. */
export function daysUntilExpiry(agent: Agent, now: Date = new Date()): number {
  const until = new Date(agent.certificate_not_after).getTime();
  return Math.floor((until - now.getTime()) / 86_400_000);
}

/**
 * Ist die Restlaufzeit ein Befund?
 *
 * Innerhalb der letzten 30 Tage erneuert der Agent selbständig — das ist der
 * vorgesehene Zustand und kein Alarm. Ein Befund ist es erst, wenn weniger als
 * eine Woche bleibt: dann haben mehrere Erneuerungsversuche gescheitert.
 */
export function certificateIsWorrying(agent: Agent, now: Date = new Date()): boolean {
  return agent.status !== "revoked" && daysUntilExpiry(agent, now) < 7;
}

/** Ein Auftrag samt Ergebnis (ohne Payload). */
export interface ConnectorJobDetail {
  id: string;
  method: string;
  state: JobState;
  result: unknown;
  error: string | null;
}

/**
 * Verbindungstest: ein Auftrag `probe_service_connection_detailed` an den
 * Agenten. Er bindet sich als Maschinenkonto des DC (Kerberos) ans AD und meldet, ob es ging
 * und wenn nicht, warum — ohne Benutzerdaten zu lesen.
 */
export function startConnectionTest(tenantId: string): Promise<ConnectorJob> {
  return post(`/api/tenants/${tenantId}/jobs`, {
    method: "probe_service_connection_detailed",
    payload: {},
  });
}

export function getConnectorJob(tenantId: string, jobId: string): Promise<ConnectorJobDetail> {
  return get(`/api/tenants/${tenantId}/jobs/${jobId}`);
}

/**
 * Was der Agent auf dem DC darf — gepflegt hier, geholt vom Agenten
 * (ADR-0014, Nachtrag „Agent auf dem DC").
 */
export interface ConnectorSettings {
  allowed_ous: string[];
  protected_groups: string[];
  updated_at: string | null;
  updated_by: string | null;
}

export function getConnectorSettings(tenantId: string): Promise<ConnectorSettings> {
  return get(`/api/tenants/${tenantId}/connector-settings`);
}

export function putConnectorSettings(
  tenantId: string,
  body: { allowed_ous: string[]; protected_groups: string[] },
): Promise<ConnectorSettings> {
  return put(`/api/tenants/${tenantId}/connector-settings`, body);
}
