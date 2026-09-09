import { get, post } from "./client";

export type Channel = "stable" | "latest";
export type UpdateStatus = "pending" | "in_progress" | "completed" | "failed" | "cancelled";

export interface Instance {
  id: string;
  slug: string;
  display_name: string;
  base_url: string;
  channel: Channel;
  deployed_version: string | null;
  latest_available_version: string | null;
  last_health_status: string | null;
  last_health_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UpdateRequest {
  id: string;
  instance_id: string;
  target_version: string;
  status: UpdateStatus;
  note: string | null;
  requested_by: string | null;
  requested_at: string;
  completed_at: string | null;
  last_error: string | null;
}

export function listInstances(): Promise<Instance[]> {
  return get("/api/instances");
}

export function pollInstance(id: string): Promise<Instance> {
  return post(`/api/instances/${id}/poll`);
}

export function listUpdateRequests(instanceId?: string): Promise<UpdateRequest[]> {
  const qs = instanceId ? `?instance_id=${instanceId}` : "";
  return get(`/api/update-requests${qs}`);
}

export function requestUpdate(instanceId: string, note?: string): Promise<UpdateRequest> {
  return post(`/api/update-requests/instance/${instanceId}`, { note: note ?? null });
}

export function cancelUpdateRequest(id: string): Promise<UpdateRequest> {
  return post(`/api/update-requests/${id}/cancel`);
}
