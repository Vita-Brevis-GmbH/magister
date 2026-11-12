import { get, post } from "./client";

export interface OperatorAccessGrant {
  jti: string;
  operator: string;
  reason: string;
  ticket: string | null;
  issued_at: string;
  expires_at: string;
}

export interface OperatorAccessOpened extends Pick<OperatorAccessGrant, "jti"> {
  /**
   * Der Einlöseschein. Er kommt **einmal** und wird nicht gespeichert — nach
   * sechzig Sekunden ist er wertlos.
   */
  assertion: string;
  expires_at: string;
  /** Die Adresse mit dem Schein im Fragment (nicht in der Abfrage). */
  redeem_url: string;
}

export interface OperatorAccessRequest {
  reason: string;
  ticket?: string | null;
}

export function openOperatorAccess(
  tenantId: string,
  body: OperatorAccessRequest,
): Promise<OperatorAccessOpened> {
  return post(`/api/tenants/${tenantId}/operator-access`, body);
}

export function listOperatorAccess(tenantId: string): Promise<OperatorAccessGrant[]> {
  return get(`/api/tenants/${tenantId}/operator-access`);
}
