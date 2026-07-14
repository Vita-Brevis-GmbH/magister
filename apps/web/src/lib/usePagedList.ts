import { useState } from "react";

export const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;

export interface PagedList<T> {
  pageItems: T[];
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  prev: () => void;
  next: () => void;
  setPageSize: (n: number) => void;
}

/** Client-side pagination for an already-loaded array. The current page is
 *  clamped to the available range, so shrinking the list (delete/archive/
 *  filter) never leaves the view stranded on an empty page. */
export function usePagedList<T>(items: T[], initialSize = 50): PagedList<T> {
  const [pageSize, setPageSizeState] = useState<number>(initialSize);
  const [page, setPage] = useState(1); // 1-based

  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * pageSize;

  return {
    pageItems: items.slice(start, start + pageSize),
    page: current,
    totalPages,
    total,
    pageSize,
    prev: () => setPage(Math.max(1, current - 1)),
    next: () => setPage(Math.min(totalPages, current + 1)),
    setPageSize: (n: number) => {
      setPageSizeState(n);
      setPage(1);
    },
  };
}
