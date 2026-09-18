export type Tone = "ok" | "warn" | "bad" | "neutral" | "busy";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-green-100 text-green-800",
  warn: "bg-amber-100 text-amber-900",
  bad: "bg-red-100 text-red-800",
  neutral: "bg-slate-100 text-slate-700",
  busy: "bg-blue-100 text-blue-800",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: string }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * Zustand → Farbe, an einer Stelle.
 *
 * Die Zuordnung ist bewusst hier und nicht in jeder Ansicht: `suspended` soll
 * überall dieselbe Farbe haben, sonst liest man die Liste falsch. Ein
 * unbekannter Zustand wird neutral — kein Absturz, aber auch keine erfundene
 * Beruhigung in Grün.
 */
const TONES: Record<string, Tone> = {
  // Kunden
  active: "ok",
  provisioning: "busy",
  suspended: "warn",
  archived: "neutral",
  // Aufträge und Sicherungen
  succeeded: "ok",
  verified: "ok",
  written: "ok",
  done: "ok",
  running: "busy",
  queued: "busy",
  claimed: "busy",
  requested: "busy",
  restored: "ok",
  switched: "ok",
  ready: "ok",
  downloaded: "ok",
  failed: "bad",
  expired: "bad",
  discarded: "neutral",
  pruned: "neutral",
  // Agenten
  online: "ok",
  enrolled: "ok",
  stale: "warn",
  revoked: "bad",
  // Offboarding
  export_ready: "busy",
  dropped: "warn",
  shredded: "warn",
  purged: "neutral",
  aborted: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={TONES[status] ?? "neutral"}>{status}</Badge>;
}
