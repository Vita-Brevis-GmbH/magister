import { cn } from "@/lib/utils";

interface Props {
  tone: "ok" | "muted" | "warn" | "danger";
  children: React.ReactNode;
  className?: string;
}

const TONE: Record<Props["tone"], string> = {
  ok: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  muted: "bg-slate-100 text-slate-600 ring-slate-200",
  warn: "bg-amber-50 text-amber-700 ring-amber-200",
  danger: "bg-rose-50 text-rose-700 ring-rose-200",
};

/** Small rounded-rectangle status badge used for "Aktiv / Deaktiviert /
 *  Archiviert" labels. Designed to read at a glance without depending on
 *  colour alone (the text carries the meaning too). */
export function StatusPill({ tone, children, className }: Props): JSX.Element {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
