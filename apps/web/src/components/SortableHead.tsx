import { TableHead } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { SortState } from "@/lib/useSortable";

/**
 * A clickable column header that drives {@link useSortable}. Shows an arrow on
 * the active column and toggles asc/desc on click. Pass `align="right"` for
 * numeric columns so the label + arrow hug the right edge.
 */
export function SortableHead({
  sortKey,
  sort,
  onSort,
  align = "left",
  className,
  children,
}: {
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  align?: "left" | "right";
  className?: string;
  children: React.ReactNode;
}): JSX.Element {
  const active = sort.key === sortKey;
  const arrow = active ? (sort.dir === "asc" ? "↑" : "↓") : "";
  return (
    <TableHead className={cn(align === "right" && "text-right", className)}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
        className={cn(
          "inline-flex items-center gap-1 font-medium transition-colors hover:text-foreground",
          align === "right" && "flex-row-reverse",
          active && "text-foreground",
        )}
      >
        <span>{children}</span>
        <span className="w-3 text-xs">{arrow}</span>
      </button>
    </TableHead>
  );
}
