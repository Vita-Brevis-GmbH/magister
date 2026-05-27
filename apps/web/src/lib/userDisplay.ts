/**
 * Shared helpers to render a user-cache row as a human label / initials.
 * Kept in lib (not components/) because they're pure string utilities.
 */

import type { AdUserOut, CurrentUserOut } from "@/api/types";

interface NamedRow {
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string;
}

/** Best-effort "Vorname Nachname" / displayName / UPN fallback. */
export function displayLabel(row: NamedRow | AdUserOut | CurrentUserOut): string {
  if (row.display_name) return row.display_name;
  const parts = [row.given_name, row.surname].filter(Boolean) as string[];
  if (parts.length > 0) return parts.join(" ");
  return row.upn;
}

/** Two-letter initials for the avatar bubble. Falls back to the UPN's first char. */
export function initials(row: NamedRow): string {
  const candidates = [row.given_name?.[0], row.surname?.[0]].filter(Boolean) as string[];
  if (candidates.length >= 2) return (candidates[0] + candidates[1]).toUpperCase();
  if (row.display_name) {
    const parts = row.display_name.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
    }
    if (parts.length === 1) {
      return parts[0]!.slice(0, 2).toUpperCase();
    }
  }
  return row.upn.slice(0, 2).toUpperCase();
}

/** Deterministic Tailwind colour class from a string — keeps the avatar
 *  bubble stable across renders without storing extra state. */
export function avatarPalette(seed: string): string {
  const palette = [
    "bg-sky-100 text-sky-700",
    "bg-emerald-100 text-emerald-700",
    "bg-amber-100 text-amber-700",
    "bg-violet-100 text-violet-700",
    "bg-rose-100 text-rose-700",
    "bg-cyan-100 text-cyan-700",
    "bg-lime-100 text-lime-700",
    "bg-indigo-100 text-indigo-700",
  ];
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) | 0;
  }
  return palette[Math.abs(h) % palette.length]!;
}
