/** Typed views of the backend's Pydantic response schemas. */

export interface CurrentUserOut {
  ad_object_guid: string;
  upn: string;
  given_name: string | null;
  surname: string | null;
  is_admin: boolean;
  school_scope: number[];
  roles: string[];
  expires_at: string;
}

export interface AuthCapabilities {
  oidc_enabled: boolean;
  local_login_enabled: boolean;
}

export interface LocalLoginRequest {
  username: string;
  password: string;
}

export interface LocalAdminOut {
  username: string;
  enabled: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  password_changed_at: string;
}

export interface LocalAdminPasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export type SchoolClassStatus = "active" | "archived";

export interface ClassOut {
  id: number;
  school_id: number;
  name: string;
  kuerzel: string | null;
  jahrgangsstufe: number;
  status: SchoolClassStatus;
  created_at: string;
  updated_at: string;
}

export interface AdUserOut {
  ad_object_guid: string;
  school_id: number | null;
  upn: string;
  given_name: string | null;
  surname: string | null;
  mail: string | null;
  kind: "teacher" | "student" | "admin";
  enabled: boolean;
  last_sync_at: string | null;
}

export interface AdUserListResponse {
  items: AdUserOut[];
  total: number;
  offset: number;
  limit: number;
  last_sync_at: string | null;
}

export type StudentPasswordResetMode = "generate" | "manual";

export interface StudentPasswordResetRequest {
  mode: StudentPasswordResetMode;
  manual_password?: string;
  force_change?: boolean;
}

export interface StudentPasswordResetResponse {
  mode: StudentPasswordResetMode;
  force_change: boolean;
  /** Set only when mode="generate"; never returned a second time. */
  temp_password: string | null;
}

export interface AppSettingsOut {
  version: number;
  oidc_issuer: string | null;
  oidc_client_id: string | null;
  oidc_client_secret_set: boolean;
  oidc_redirect_uri: string | null;
  oidc_scopes: string[];
  bootstrap_admins: string[];
  ad_dcs: string[];
  ad_bind_dn: string | null;
  ad_bind_password_set: boolean;
  ad_users_search_base: string | null;
  ad_sync_interval_minutes: number;
  updated_at: string;
  updated_by_upn: string | null;
}

/** Send `null`/omitted to leave fields untouched. The two secret fields are
 *  only updated when a non-empty string is sent — empty string is a no-op. */
export interface AppSettingsUpdate {
  oidc_issuer?: string | null;
  oidc_client_id?: string | null;
  oidc_client_secret?: string | null;
  oidc_redirect_uri?: string | null;
  oidc_scopes?: string[] | null;
  bootstrap_admins?: string[] | null;
  ad_dcs?: string[] | null;
  ad_bind_dn?: string | null;
  ad_bind_password?: string | null;
  ad_users_search_base?: string | null;
  ad_sync_interval_minutes?: number | null;
}
