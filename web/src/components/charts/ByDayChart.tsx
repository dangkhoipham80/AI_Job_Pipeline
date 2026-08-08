import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TooltipBox, axisColor, gridColor } from "@/components/charts/ChartFrame";
import { shortDay } from "@/lib/format";

// Change-over-time (jobs crawled per day) → single-series bars, sequential blue.
// Title names the series, so no legend box.
export function ByDayChart({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data)
    .map(([day, count]) => ({ day, count }))
    .sort((a, b) => a.day.localeCompare(b.day))
    .slice(-14);

  if (rows.length === 0) return <Empty />;

  return (
    <ResponsiveContainer width="100%" height={180}>
      {/* left: -18 pulled the Y tick labels past the plot edge — "50" rendered
          as "0". Trim the axis width instead of shifting it off-canvas. */}
      <BarChart data={rows} margin={{ left: -8, right: 8, top: 8, bottom: 4 }}>
        <CartesianGrid vertical={false} stroke={gridColor()} strokeDasharray="0" />
        <XAxis
          dataKey="day"
          axisLine={false}
          tickLine={false}
          tick={{ fill: axisColor(), fontSize: 11 }}
          tickFormatter={shortDay}
          minTickGap={12}
        />
        <YAxis
          axisLine={false}
          tickLine={false}
          width={30}
          allowDecimals={false}
          tick={{ fill: axisColor(), fontSize: 11 }}
        />
        <Tooltip
          cursor={{ fill: "rgba(120,120,120,0.08)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                label={shortDay(String(payload[0].payload.day))}
                rows={[{ key: "crawled", value: payload[0].value as number, color: "#3987e5" }]}
              />
            ) : null
          }
        />
        <Bar dataKey="count" fill="#3987e5" radius={[3, 3, 0, 0]} maxBarSize={26} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Empty() {
  return <div className="grid h-40 place-items-center text-sm text-ink-muted">No crawl history yet.</div>;
}
