import { useMemo, useRef, useState } from "react";

export type SortDir = "asc" | "desc";

export interface SortState {
  key: string;
  dir: SortDir;
}

/** Value a column contributes to the sort. `null`/`undefined` always sort last. */
export type SortValue = string | number | boolean | null | undefined;

export type SortAccessors<T> = Record<string, (item: T) => SortValue>;

const collator = new Intl.Collator("de", { sensitivity: "base", numeric: true });

function compareValues(a: SortValue, b: SortValue): number {
  const aEmpty = a === null || a === undefined || a === "";
  const bEmpty = b === null || b === undefined || b === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1; // empties always last, regardless of direction flip below
  if (bEmpty) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return a === b ? 0 : a ? -1 : 1;
  return collator.compare(String(a), String(b));
}

export interface Sortable<T> {
  sorted: T[];
  sort: SortState;
  toggle: (key: string) => void;
}

/**
 * Client-side, locale-aware sorting for an already-loaded list.
 *
 * Lists default to the first column ascending; clicking a column header sorts
 * by it and toggles asc/desc. Empty values (null/blank) always sort last so a
 * missing field never floats to the top. The output array is stable across
 * renders as long as `items` and the active sort don't change, so it can feed
 * `usePagedList` without churn.
 */
export function useSortable<T>(
  items: T[],
  accessors: SortAccessors<T>,
  defaultKey: string,
  defaultDir: SortDir = "asc",
): Sortable<T> {
  const [sort, setSort] = useState<SortState>({ key: defaultKey, dir: defaultDir });

  // Keep accessors out of the memo deps: callers pass a fresh object literal
  // each render, but the sort only needs the latest closure at compute time.
  const accRef = useRef(accessors);
  accRef.current = accessors;

  const toggle = (key: string): void =>
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );

  const sorted = useMemo(() => {
    const acc = accRef.current[sort.key];
    if (!acc) return items;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...items].sort((a, b) => factor * compareValues(acc(a), acc(b)));
  }, [items, sort]);

  return { sorted, sort, toggle };
}
