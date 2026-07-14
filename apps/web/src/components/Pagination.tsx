import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { PAGE_SIZE_OPTIONS, type PagedList } from "@/lib/usePagedList";

/** Prev/next pager + page-size selector for a {@link usePagedList} result.
 *  Renders nothing when there are no items. */
export function Pagination<T>({ paged, busy }: { paged: PagedList<T>; busy?: boolean }): JSX.Element {
  const { t } = useTranslation();
  if (paged.total === 0) return <></>;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">
          {t("common.pagination_info", {
            page: paged.page,
            total: paged.totalPages,
            count: paged.total,
          })}
        </span>
        <label className="flex items-center gap-1.5 text-muted-foreground">
          {t("common.per_page")}
          <select
            value={paged.pageSize}
            onChange={(e) => paged.setPageSize(Number(e.target.value))}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={paged.page <= 1 || busy}
          onClick={paged.prev}
        >
          {t("common.pagination_prev")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={paged.page >= paged.totalPages || busy}
          onClick={paged.next}
        >
          {t("common.pagination_next")}
        </Button>
      </div>
    </div>
  );
}
