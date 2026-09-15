import { get, post } from "./client";

/**
 * Die Anmeldung an der Konsole (ADR-0020, ADR-0023).
 *
 * Zwei erste Faktoren führen zum selben zweiten:
 *
 * - **Passwort** (ADR-0023 D1, der Normalfall). `login()` prüft es und legt
 *   einen Zwischenstand an, der zu nichts berechtigt ausser dem Code.
 * - **Client-Zertifikat** (ADR-0020 D1). Das passiert vor der Anwendung, im
 *   Reverse Proxy; die Oberfläche sieht davon nichts.
 *
 * Welcher Schritt fehlt, beantwortet in beiden Fällen der Server: er sieht
 * Zertifikat und Sitzung, der Browser nicht.
 */
export type AuthStage =
  /**
   * Niemand erkannt: noch keine Anmeldung, kein Zertifikat oder ein
   * unbekanntes — der Server sagt nicht, welches davon. Der Name stammt aus
   * ADR-0020 und bleibt, damit der Vertrag stabil ist.
   */
  | "unknown_certificate"
  | "enrolment_required"
  | "totp_required"
  | "authenticated"
  | "locked";

export interface Whoami {
  stage: AuthStage;
  /** Erst gesetzt, sobald das Zertifikat bekannt ist. */
  upn: string | null;
  name: string | null;
  expires_at: string | null;
}

export interface Enrolment {
  secret: string;
  provisioning_uri: string;
  qr_data_uri: string;
  recovery_codes: string[];
}

/**
 * Erster Faktor mit Passwort (ADR-0023 D1).
 *
 * Die Antwort ist **keine** Anmeldung: sie sagt, welcher Schritt jetzt fehlt
 * — in aller Regel der Code. Ein 401 bedeutet „unbekannt, falsch oder
 * gesperrt"; welches davon, sagt der Server absichtlich nicht.
 */
export function login(upn: string, password: string): Promise<Whoami> {
  return post("/api/auth/console/login", { upn, password });
}

export function whoami(): Promise<Whoami> {
  return get("/api/auth/console/whoami");
}

export function beginEnrolment(): Promise<Enrolment> {
  return post("/api/auth/console/enrol");
}

export function submitCode(code: string): Promise<Whoami> {
  return post("/api/auth/console/totp", { code });
}

export function logout(): Promise<void> {
  return post("/api/auth/console/logout");
}
