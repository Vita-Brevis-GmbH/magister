import { get } from "./client";

/**
 * Befunde über die Connector-Flotte (ADR-0021 D6).
 *
 * Nichts davon ist gespeichert: die Konsole rechnet bei jeder Anfrage. Ein
 * gespeicherter Befund müsste quittiert und aufgeräumt werden — und wäre
 * spätestens dann falsch, wenn sich der Agent wieder gemeldet hat.
 */
export type Severity = "warning" | "critical";

export interface FleetFinding {
  /** Maschinenlesbar; die Ansicht gruppiert danach. */
  kind: string;
  severity: Severity;
  tenant_slug: string;
  agent_name: string | null;
  /** Für Menschen, mit dem nächsten Schritt darin. */
  detail: string;
}

export interface FleetReport {
  findings: FleetFinding[];
  /**
   * Derselbe Wert, den `cockpit_api.cli.fleet_check` als Exit-Code liefert:
   * 0 in Ordnung, 1 Warnung, 2 kritisch. Er kommt vom Server, damit die
   * Ansicht den Schweregrad nicht anders rechnet als die Überwachung.
   */
  worst: number;
}

export function getFleetReport(): Promise<FleetReport> {
  return get("/api/fleet/findings");
}
