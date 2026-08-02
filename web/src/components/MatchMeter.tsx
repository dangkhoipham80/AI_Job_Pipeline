import { matchPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { JobQuality } from "@/types";

/** The arithmetic behind the number, as a tooltip. */
function explain(quality?: JobQuality | null): string | undefined {
  const matched = quality?.matched ?? [];
  const missing = quality?.missing ?? [];
  if (!matched.length && !missing.length) return undefined;
  const lines: string[] = [];
  if (matched.length) lines.push(`Mentions: ${matched.join(", ")}`);
  if (missing.length) lines.push(`Doesn't mention: ${missing.join(", ")}`);
  return lines.join("\n");
}

// Sequential magnitude (0..100%) as a single-hue meter — blue, light→dark by
// value. Tabular figure so rows align.
//
// The tooltip carries the reasons: a bare "25%" is a verdict with no argument
// attached, and the score comes from a list you configured, so naming that list
// is what makes it reviewable.
export function MatchMeter({
  score,
  quality,
  className,
}: {
  score: number;
  quality?: JobQuality | null;
  className?: string;
}) {
  const pct = matchPercent(score);
  const hue = pct >= 66 ? "#256abf" : pct >= 33 ? "#3987e5" : "#86b6ef";
  const why = explain(quality);
  return (
    <div
      className={cn("flex items-center gap-2", className)}
      title={why ? `Match ${pct}%\n${why}` : `Match ${pct}%`}
    >
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink/10">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: hue }} />
      </div>
      <span className="w-8 font-mono text-[11px] tabular-nums text-ink-muted">{pct}%</span>
    </div>
  );
}

const FLAG_LABEL: Record<string, { short: string; why: string }> = {
  no_jd: { short: "no JD", why: "No description — paste one in before tailoring." },
  thin_jd: {
    short: "thin JD",
    why: "Very short description; there may not be enough here to tailor against.",
  },
  stale: { short: "old", why: "Posted a while ago; the role may already be filled." },
  undated: { short: "undated", why: "The source didn't publish a date, so freshness is unknown." },
};

/**
 * Advisory badges. These never hide a job — they annotate it and leave the
 * decision with you, the same way the crawler surfaces a gap rather than
 * quietly closing it.
 */
export function QualityFlags({
  quality,
  className,
}: {
  quality?: JobQuality | null;
  className?: string;
}) {
  const flags = quality?.flags ?? [];
  if (!flags.length) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      {flags.map((f) => {
        const meta = FLAG_LABEL[f] ?? { short: f, why: f };
        return (
          <span
            key={f}
            title={meta.why}
            className="rounded border border-caution/40 bg-caution/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-caution"
          >
            {meta.short}
          </span>
        );
      })}
    </div>
  );
}
