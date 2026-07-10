// Shared tooltip styling so both charts read as one system.
export function TooltipBox({
  label,
  rows,
}: {
  label: string;
  rows: { key: string; value: React.ReactNode; color?: string }[];
}) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{label}</div>
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-2 text-ink-muted">
          {r.color && <span className="h-2 w-2 rounded-sm" style={{ background: r.color }} />}
          <span className="tabular-nums text-ink">{r.value}</span>
          <span>{r.key}</span>
        </div>
      ))}
    </div>
  );
}

export function axisColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--ink-muted").trim() || "#898781";
}
export function gridColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--grid").trim() || "#e1e0d9";
}
