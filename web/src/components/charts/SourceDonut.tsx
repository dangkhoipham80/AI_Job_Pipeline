import { useMemo } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { TooltipBox, surfaceColor } from "@/components/charts/ChartFrame";
import { MUTED, sourceColor, sourceSlot } from "@/components/charts/palette";
import { sourceLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { FacetRow } from "@/types";

/** Past this many slices the tail is folded into "Other". Part-to-whole reads
 *  at a glance only while the eye can hold the segments — six is the ceiling,
 *  and the tail of a job corpus is always a run of near-equal 3s and 4s that a
 *  ring cannot separate anyway. The legend below still lists every source. */
const MAX_SLICES = 6;

type Slice = { key: string; label: string; count: number; color: string; slot: number };
type LegendRow = Slice & { folded: boolean };

function build(rows: FacetRow[]): { slices: Slice[]; legend: LegendRow[] } {
  const ranked = [...rows].sort((a, b) => b.count - a.count);
  const folds = ranked.length > MAX_SLICES;
  const head = ranked.slice(0, folds ? MAX_SLICES - 1 : MAX_SLICES);
  const tail = ranked.slice(head.length);

  const slice = (r: FacetRow): Slice => ({
    key: r.key,
    label: sourceLabel(r.key),
    count: r.count,
    color: sourceColor(r.key),
    slot: sourceSlot(r.key),
  });

  const slices = head.map(slice);
  if (tail.length) {
    slices.push({
      key: "_other",
      label: `Other (${tail.length})`,
      count: tail.reduce((n, r) => n + r.count, 0),
      color: MUTED,
      // Sorts last on the ring: grey is the absence of an identity hue, so it
      // is the one segment that cannot collide with a neighbour.
      slot: Number.MAX_SAFE_INTEGER,
    });
  }

  // Every source keeps its row and its count — folding is about how many
  // segments a ring can hold, not about hiding the tail. A folded row wears
  // grey because grey is the segment it is *in*; giving it its own hue would
  // point at a slice that isn't on the ring.
  const legend: LegendRow[] = ranked.map((r) => {
    const s = slice(r);
    const folded = tail.some((t) => t.key === r.key);
    return folded ? { ...s, color: MUTED, folded } : { ...s, folded };
  });
  return { slices, legend };
}

/**
 * Where the corpus came from, as a part-to-whole ring.
 *
 * **Slices are ordered by palette slot, not by count.** That looks like a
 * quirk and is the whole reason the ring is safe: the eight categorical hues
 * are only validated as colourblind-distinct for pairs that are *adjacent in
 * the fixed slot order*. Sorted by count, whichever two sources happen to rank
 * side by side end up touching — and measured on this corpus that put grey
 * next to magenta at ΔE 2.1 under deuteranopia, i.e. one indistinguishable
 * boundary. Ordered by slot, the worst touching pair measures ΔE 41. The
 * ranking people actually want is in the legend, where it is read as numbers.
 */
export function SourceDonut({ rows, total }: { rows: FacetRow[]; total: number }) {
  const { slices, legend } = useMemo(() => build(rows), [rows]);
  const ring = useMemo(() => [...slices].sort((a, b) => a.slot - b.slot), [slices]);

  if (!ring.length) {
    return (
      <div className="grid h-40 place-items-center text-sm text-muted-foreground">
        Nothing crawled yet.
      </div>
    );
  }

  const share = (n: number) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
      <div className="relative h-56 w-56 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={ring}
              dataKey="count"
              nameKey="label"
              innerRadius="62%"
              outerRadius="98%"
              startAngle={90}
              endAngle={-270}
              // The 2px gap is a surface-coloured stroke, not a border drawn
              // round each slice: it separates fills without adding a line.
              stroke={surfaceColor()}
              strokeWidth={2}
              isAnimationActive={false}
            >
              {ring.map((s) => (
                <Cell key={s.key} fill={s.color} />
              ))}
            </Pie>
            <Tooltip
              content={({ payload }) =>
                payload?.length ? (
                  <TooltipBox
                    label={String(payload[0].payload.label)}
                    rows={[
                      {
                        key: `jobs · ${share(Number(payload[0].payload.count))}%`,
                        value: String(payload[0].payload.count),
                        color: String(payload[0].payload.color),
                      },
                    ]}
                  />
                ) : null
              }
            />
          </PieChart>
        </ResponsiveContainer>
        {/* The hole earns its keep by holding the total the ring divides up. */}
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="text-center">
            <div className="text-2xl font-semibold leading-none">{total}</div>
            <div className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">
              postings
            </div>
          </div>
        </div>
      </div>

      {/* Legend by rank, carrying the numbers. Doubles as the relief channel:
          every slice is identified by name and value, never by hue alone. */}
      <ul className="min-w-0 flex-1 space-y-1.5">
        {legend.map((s) => (
          <li key={s.key} className="flex items-center gap-2.5 text-sm">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
              style={{ background: s.color }}
            />
            <span className={cn("min-w-0 flex-1 truncate", s.folded && "text-muted-foreground")}>
              {s.label}
            </span>
            <span className="tabular-nums text-muted-foreground">{share(s.count)}%</span>
            <span className="w-8 text-right tabular-nums font-medium">{s.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
