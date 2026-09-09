import { useState } from "react";

interface Props {
  /** Was das ist — „Rollenpasswort", „Kundenschlüssel". */
  label: string;
  /** Der Wert. Er existiert nur in diesem Fenster und in diesem Moment. */
  value: string;
  /** Wohin er gehört, im Klartext. */
  destination: string;
  /** Warum ihn zu verlieren teuer ist. */
  consequence: string;
  /**
   * Wird gerufen, wenn bestätigt ist, dass der Wert im Passwortspeicher liegt.
   *
   * Der Zustand liegt bewusst **beim Aufrufer** und nicht hier: die Ansicht,
   * die ein Geheimnis zeigt, muss wissen, ob noch eines offen ist — sonst
   * baut man einen „Fertig"-Knopf, der nie klickbar wird. Genau das war der
   * erste Entwurf.
   */
  onAcknowledged: () => void;
}

/**
 * Ein Geheimnis, das genau **einmal** kommt.
 *
 * Rollenpasswort und Kundenschlüssel liefert die API bei der Bereitstellung
 * beziehungsweise beim Drehen — und danach nie wieder. Sie stehen auch nicht
 * in der Konsolen-Datenbank.
 *
 * Deshalb ist dieser Baustein absichtlich unbequem:
 *
 * * Er ist **nicht wegklickbar**, solange nicht bestätigt wurde, dass der Wert
 *   im Passwortspeicher liegt. Ein „×" oben rechts wäre der Handgriff, mit dem
 *   ein Kundenschlüssel verloren geht — und mit ihm die Audit-Payloads und
 *   gespeicherten Passwörter dieses Kunden.
 * * Er zeigt den Wert **verdeckt**, bis jemand hinsieht. Ein Bildschirm in
 *   einem Büro ist ein Bildschirm in einem Büro.
 * * Er sagt, **wohin** der Wert gehört, nicht nur dass er wichtig ist.
 *
 * Kopieren geht über die Zwischenablage; scheitert das (kein sicherer Kontext,
 * verweigerte Berechtigung), bleibt der Wert markierbar — der Knopf ist die
 * Bequemlichkeit, nicht der Weg.
 */
export function SecretOnce({
  label,
  value,
  destination,
  consequence,
  onAcknowledged,
}: Props) {
  const [revealed, setRevealed] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "done" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopyState("done");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <div className="mb-4 rounded border-2 border-amber-500 bg-amber-50 p-4">
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <h3 className="font-semibold text-amber-900">{label} — kommt genau einmal</h3>
        <span className="text-xs uppercase tracking-wider text-amber-700">
          nicht abrufbar, sobald diese Seite weg ist
        </span>
      </div>

      <p className="mb-3 text-sm text-amber-900">
        Gehört nach: <span className="font-mono">{destination}</span>
        <br />
        {consequence}
      </p>

      <div className="mb-3 flex items-center gap-2">
        <code
          className="flex-1 select-all break-all rounded border border-amber-300 bg-white px-2 py-1 font-mono text-sm"
          data-testid="secret-value"
        >
          {revealed ? value : "•".repeat(Math.min(value.length, 48))}
        </code>
        <button
          type="button"
          onClick={() => setRevealed((r) => !r)}
          className="rounded border border-amber-400 px-2 py-1 text-xs"
        >
          {revealed ? "Verdecken" : "Anzeigen"}
        </button>
        <button
          type="button"
          onClick={copy}
          className="rounded border border-amber-400 px-2 py-1 text-xs"
        >
          {copyState === "done" ? "Kopiert" : "Kopieren"}
        </button>
      </div>

      {copyState === "failed" && (
        <p className="mb-3 text-xs text-amber-800">
          Die Zwischenablage liess sich nicht beschreiben. Der Wert oben ist
          markierbar — anzeigen und von Hand kopieren.
        </p>
      )}

      <button
        type="button"
        onClick={onAcknowledged}
        className="rounded bg-amber-700 px-3 py-1 text-sm font-medium text-white"
      >
        Ist im Passwortspeicher — ausblenden
      </button>
    </div>
  );
}
