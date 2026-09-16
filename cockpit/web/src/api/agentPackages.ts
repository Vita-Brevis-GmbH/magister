import { ApiError, authHeaders, get } from "./client";

/**
 * Ein gebautes Paket des Connector-Agenten (ADR-0014).
 *
 * `sha256` kommt aus derselben Quelle wie die Datei — die Konsole rechnet die
 * Prüfsumme beim Auflisten über den Inhalt. Sie beantwortet „ist die Datei
 * heil angekommen?", nicht „kommt sie von Vita Brevis": das sagt die
 * Paketsignatur (Entscheid E18).
 */
export interface AgentPackage {
  filename: string;
  size_bytes: number;
  sha256: string;
  modified_at: string;
}

export function listAgentPackages(): Promise<AgentPackage[]> {
  return get("/api/agent-packages");
}

/**
 * Ein Paket herunterladen.
 *
 * Wie beim Export geht ein einfacher `<a href>` nicht: der Endpunkt hängt am
 * `Authorization`-Header, und eine Navigation des Browsers schickt keinen mit
 * — sie endete in einem 401, das wie ein fehlendes Paket aussieht.
 */
export async function downloadAgentPackage(filename: string): Promise<void> {
  const response = await fetch(`/api/agent-packages/${encodeURIComponent(filename)}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()).slice(0, 500));
  }
  const url = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Grösse in der Einheit, die ein Mensch liest. */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** Windows, Debian oder unbekannt — nach der Endung, mehr weiss die API nicht. */
export function platformOf(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".msi") || lower.endsWith(".exe")) return "Windows";
  if (lower.endsWith(".deb")) return "Debian/Ubuntu";
  return "—";
}
