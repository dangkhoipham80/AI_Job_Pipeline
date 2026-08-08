import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { sourceColor } from "@/components/charts/palette";
import { TooltipBox, axisColor } from "@/components/charts/ChartFrame";
import { titleCase } from "@/lib/format";

// Magnitude by identity → horizontal bars, one fixed hue per source (color
// follows the entity). Counts are direct-labeled, so no legend needed.
export function BySourceChart({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data)
    .map(([source, count]) => ({ source, count }))
    .sort((a, b) => b.count - a.count);

  if (rows.length === 0) return <Empty />;

  return (
    <ResponsiveContainer width="100%" height={Math.max(rows.length * 44, 88)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 28, top: 4, bottom: 4 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="source"
          axisLine={false}
          tickLine={false}
          // Fits the longest source label ("Weworkremotely"); at 92 it lost its
          // first letter, which reads as a typo rather than as clipping.
          width={110}
          tick={{ fill: axisColor(), fontSize: 12 }}
          tickFormatter={titleCase}
        />
        <Tooltip
          cursor={{ fill: "rgba(120,120,120,0.08)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                label={titleCase(String(payload[0].payload.source))}
                rows={[
                  { key: "jobs", value: payload[0].value as number, color: sourceColor(String(payload[0].payload.source)) },
                ]}
              />
            ) : null
          }
        />
        <Bar dataKey="count" radius={[4, 4, 4, 4]} barSize={18} isAnimationActive={false}>
          {rows.map((r) => (
            <Cell key={r.source} fill={sourceColor(r.source)} />
          ))}
          <LabelList
            dataKey="count"
            position="right"
            className="fill-ink"
            style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function Empty() {
  return <div className="grid h-24 place-items-center text-sm text-ink-muted">No jobs yet.</div>;
}
