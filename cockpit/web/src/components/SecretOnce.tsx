import { useEffect, useRef, useState } from "react";

import { holdSecret } from "../lib/nav";

interface Props {
  /** Was das ist — „Rollenpasswort", „Kundenschlüssel". */
  label: string;
  /** Der Wert. Er existiert nur in diesem Fenster und in diesem Moment. */
  value: string;
  /** Wohin er gehört, im Klartext. */
  destination: string;
  /** Warum ihn zu verlieren teuer ist. */
  consequence: string;
  /** Was zu tun ist, wenn er trotzdem verloren ging. */
  recovery?: string;
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
 * * Er lässt sich erst ausblenden, wenn der Wert kopiert oder angezeigt wurde
 *   **und** das Häkchen „liegt im Passwortspeicher“ gesetzt ist — zwei
 *   bewusste Handgriffe statt eines Knopfs, der sich treffen lässt.
 * * Solange er steht, fragt jeder Ansichtswechsel, Neuladen oder Schliessen
 *   nach (`holdSecret`).
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
  recovery,
  onAcknowledged,
}: Props) {
  const [revealed, setRevealed] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "done" | "failed">("idle");
  const [handled, setHandled] = useState(false);
  const [stored, setStored] = useState(false);
  const releaseRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const release = holdSecret();
    releaseRef.current = release;
    return release;
  }, []);

  function acknowledge() {
    // Erst freigeben, dann melden: der Aufrufer springt danach oft auf eine
    // andere Ansicht, und die soll nicht mehr nachfragen.
    releaseRef.current?.();
    onAcknowledged();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopyState("done");
      setHandled(true);
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
          onCopy={() => setHandled(true)}
          className="flex-1 select-all break-all rounded border border-amber-300 bg-white px-2 py-1 font-mono text-sm"
          data-testid="secret-value"
        >
          {revealed ? value : "•".repeat(Math.min(value.length, 48))}
        </code>
        <button
          type="button"
          onClick={() => {
            setRevealed((r) => !r);
            setHandled(true);
          }}
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

      <label className="mb-2 flex items-start gap-2 text-sm text-amber-900">
        <input
          type="checkbox"
          checked={stored}
          disabled={!handled}
          onChange={(e) => setStored(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          Ich habe den Wert im Passwortspeicher gespeichert und dort geprüft.
          {!handled && (
            <span className="block text-xs text-amber-700">
              Erst kopieren oder anzeigen.
            </span>
          )}
        </span>
      </label>

      <button
        type="button"
        onClick={acknowledge}
        disabled={!stored}
        className="rounded bg-amber-700 px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        Ausblenden — der Wert ist danach weg
      </button>

      {recovery && (
        <p className="mt-3 border-t border-amber-200 pt-2 text-xs text-amber-800">
          Doch verloren? {recovery}
        </p>
      )}
    </div>
  );
}
