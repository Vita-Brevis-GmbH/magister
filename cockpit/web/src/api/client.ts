// Gemeinsamer Zugang zur Konsolen-API.
//
// Ein Ort für die drei Dinge, die sonst in jedem Aufruf wiederholt würden:
// den Token, die Fehlerbehandlung und die Prüfung, ob überhaupt eine Antwort
// mit Inhalt kam.

export interface ApiErrorBody {
  detail?: unknown;
}

/** Fehler der API mit Statuscode — die Oberfläche unterscheidet danach. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${sessionStorage.getItem("cockpit_token") ?? ""}` };
}

/**
 * Die Fehlermeldung der API lesbar machen.
 *
 * FastAPI liefert `detail` — entweder als Zeichenkette oder, bei einem
 * Validierungsfehler, als Liste von Objekten. Roh angezeigt steht dann
 * `[object Object]` auf dem Bildschirm, und der eigentliche Hinweis ("slug
 * muss mit einem Buchstaben beginnen") ist unsichtbar.
 */
function readDetail(body: string): string {
  try {
    const parsed = JSON.parse(body) as ApiErrorBody;
    const detail = parsed.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            const entry = item as { msg?: unknown; loc?: unknown };
            const where = Array.isArray(entry.loc) ? entry.loc.slice(1).join(".") : "";
            return where ? `${where}: ${String(entry.msg)}` : String(entry.msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
    if (detail !== undefined) return JSON.stringify(detail);
  } catch {
    // Keine JSON-Antwort — dann ist der Rumpf selbst die beste Auskunft.
  }
  return body.slice(0, 500);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new ApiError(response.status, readDetail(await response.text()));
  }
  // 204 und ein leerer Rumpf sind gültige Antworten; `response.json()` würde
  // daran mit einem Syntaxfehler scheitern und wie ein Serverfehler aussehen.
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

export function del(path: string): Promise<void> {
  return request<void>(path, { method: "DELETE" });
}
