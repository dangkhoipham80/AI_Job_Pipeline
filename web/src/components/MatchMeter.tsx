import { matchPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

// Sequential magnitude (0..100%) as a single-hue meter — blue, light→dark by
// value. Tabular figure so rows align.
export function MatchMeter({ score, className }: { score: number; className?: string }) {
  const pct = matchPercent(score);
  const hue = pct >= 66 ? "#256abf" : pct >= 33 ? "#3987e5" : "#86b6ef";
  return (
    <div className={cn("flex items-center gap-2", className)} title={`Match ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink/10">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: hue }} />
      </div>
      <span className="w-8 font-mono text-[11px] tabular-nums text-ink-muted">{pct}%</span>
    </div>
  );
}
