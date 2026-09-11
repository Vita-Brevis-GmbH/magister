import { get, post } from "./client";

/**
 * Die Anmeldung an der Konsole (ADR-0020).
 *
 * Der erste Schritt passiert vor der Anwendung: der Reverse Proxy verlangt ein
 * Client-Zertifikat. Was hier bleibt, ist der zweite Faktor — und die Frage,
 * welcher Schritt überhaupt fehlt. Die beantwortet der Server, nicht der
 * Browser: er sieht das Zertifikat, die Oberfläche nicht.
 */
export type AuthStage =
  /** Kein oder ein unbekanntes Zertifikat — der Server sagt nicht, welches. */
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
