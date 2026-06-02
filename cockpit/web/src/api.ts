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

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${localStorage.getItem("cockpit_token") ?? ""}` };
}

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function listInstances(): Promise<Instance[]> {
  return jsonOrThrow(await fetch("/api/instances", { headers: authHeaders() }));
}

export async function pollInstance(id: string): Promise<Instance> {
  return jsonOrThrow(
    await fetch(`/api/instances/${id}/poll`, { method: "POST", headers: authHeaders() }),
  );
}

export async function listUpdateRequests(instanceId?: string): Promise<UpdateRequest[]> {
  const qs = instanceId ? `?instance_id=${instanceId}` : "";
  return jsonOrThrow(await fetch(`/api/update-requests${qs}`, { headers: authHeaders() }));
}

export async function requestUpdate(
  instanceId: string,
  note?: string,
): Promise<UpdateRequest> {
  return jsonOrThrow(
    await fetch(`/api/update-requests/instance/${instanceId}`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ note: note ?? null }),
    }),
  );
}

export async function cancelUpdateRequest(id: string): Promise<UpdateRequest> {
  return jsonOrThrow(
    await fetch(`/api/update-requests/${id}/cancel`, { method: "POST", headers: authHeaders() }),
  );
}
