// Display helpers. Interface voice: plain, specific, end-user facing.

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function shortDay(iso: string): string {
  // "2026-07-10" -> "Jul 10"
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** "today 14:32" / "Jul 26 09:05" — for "when exactly did that crawl run?". */
export function clockTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  const day = d.toDateString() === new Date().toDateString()
    ? "today"
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${day} ${time}`;
}

export function matchPercent(score: number): number {
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

export function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
