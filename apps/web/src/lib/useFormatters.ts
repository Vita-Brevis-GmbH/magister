import { useMemo } from "react";

import { useMyPreferences } from "@/api/hooks";
import { DEFAULT_PREFS, makeFormatters, type Formatters } from "@/lib/format";

/** Formatters bound to the current user's preferences (defaults until loaded). */
export function useFormatters(): Formatters {
  const prefs = useMyPreferences();
  return useMemo(() => makeFormatters(prefs.data ?? DEFAULT_PREFS), [prefs.data]);
}
