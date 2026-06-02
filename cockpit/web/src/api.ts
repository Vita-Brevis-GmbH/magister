export type Channel = "stable" | "latest";

export interface Instance {
  id: string;
  slug: string;
  display_name: string;
  base_url: string;
  channel: Channel;
  deployed_version: string | null;
  last_health_status: string | null;
  last_health_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

function token(): string {
  return localStorage.getItem("cockpit_token") ?? "";
}

export async function listInstances(): Promise<Instance[]> {
  const r = await fetch("/api/instances", {
    headers: { Authorization: `Bearer ${token()}` },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function pollInstance(id: string): Promise<Instance> {
  const r = await fetch(`/api/instances/${id}/poll`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token()}` },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
