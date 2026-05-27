import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

/** Generic loading placeholder. Compose by varying `className` (h-4 w-32 etc). */
export function Skeleton({ className }: Props): JSX.Element {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block animate-pulse rounded-md bg-muted/70", className)}
    />
  );
}

/** Convenience helper for table-row loading state. */
export function SkeletonRow({ columns }: { columns: number }): JSX.Element {
  return (
    <tr>
      {Array.from({ length: columns }).map((_, i) => (
        <td key={i} className="py-3">
          <Skeleton className="h-4 w-full max-w-[180px]" />
        </td>
      ))}
    </tr>
  );
}
