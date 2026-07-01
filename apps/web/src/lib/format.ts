/**
 * Locale-aware formatting driven by the user's saved preferences
 * (language, region, date_format, time_format). Dates use the explicitly
 * chosen pattern; time honours 12h/24h; numbers use the language-region locale.
 */
import type { PrefDateFormat, UserPreferencesOut } from "@/api/types";

export const DEFAULT_PREFS: UserPreferencesOut = {
  language: "de",
  region: "CH",
  date_format: "DD.MM.YYYY",
  time_format: "24h",
};

export interface Formatters {
  /** Date only, in the user's chosen pattern. Empty/invalid input passes through. */
  formatDate(iso: string | null | undefined): string;
  /** Date + time (time in the user's 12h/24h preference). */
  formatDateTime(iso: string | null | undefined): string;
  /** Number in the user's language-region locale. */
  formatNumber(value: number): string;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function datePart(d: Date, fmt: PrefDateFormat): string {
  const dd = pad2(d.getDate());
  const mm = pad2(d.getMonth() + 1);
  const yyyy = String(d.getFullYear());
  switch (fmt) {
    case "YYYY-MM-DD":
      return `${yyyy}-${mm}-${dd}`;
    case "MM/DD/YYYY":
      return `${mm}/${dd}/${yyyy}`;
    default:
      return `${dd}.${mm}.${yyyy}`;
  }
}

export function makeFormatters(prefs: UserPreferencesOut): Formatters {
  const locale = `${prefs.language}-${prefs.region}`;
  const timeFmt = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: prefs.time_format === "12h",
  });
  const numberFmt = new Intl.NumberFormat(locale);

  function parse(iso: string | null | undefined): Date | null {
    if (!iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  return {
    formatDate(iso) {
      const d = parse(iso);
      return d ? datePart(d, prefs.date_format) : (iso ?? "");
    },
    formatDateTime(iso) {
      const d = parse(iso);
      return d ? `${datePart(d, prefs.date_format)} ${timeFmt.format(d)}` : (iso ?? "");
    },
    formatNumber(value) {
      return numberFmt.format(value);
    },
  };
}
