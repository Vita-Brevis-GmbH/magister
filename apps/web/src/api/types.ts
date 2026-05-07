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
