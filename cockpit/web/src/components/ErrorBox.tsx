import { ApiError } from "../api/client";

/**
 * Ein Fehler, wie ihn jemand lesen kann, der ihn beheben soll.
 *
 * Drei Fälle werden unterschieden, weil sie drei verschiedene Handgriffe
 * verlangen:
 *
 * * **401** — der Token fehlt oder ist falsch. Kein Serverfehler, sondern ein
 *   Feld oben rechts.
 * * **409** — die Reihenfolge stimmt nicht (ein Schritt vor seinem
 *   Vorgänger, eine Frist noch nicht abgelaufen). Die API sagt in `detail`,
 *   was fehlt; das ist die Auskunft, die zählt.
 * * alles andere — mit Statuscode, damit man weiss, ob man selbst gemeint ist.
 */
export function ErrorBox({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return (
        <div className="mb-3 rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          <span className="font-medium">Nicht angemeldet.</span> Den Bootstrap-Token oben
          rechts setzen. Er steht auf dem Anwendungsserver in der Umgebung der Konsole.
        </div>
      );
    }
    return (
      <div className="mb-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
        <span className="font-medium">
          {error.status === 409 ? "Reihenfolge" : `HTTP ${error.status}`}:
        </span>{" "}
        {error.message}
      </div>
    );
  }
  return (
    <div className="mb-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}
