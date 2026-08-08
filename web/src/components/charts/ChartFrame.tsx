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

function token(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// `--ink-muted` is stored as RGB *channels* ("157 155 144") so Tailwind can
// compose `rgb(var(--ink-muted) / <alpha-value>)`. Handed to SVG raw, that
// string is not a colour: the `fill` attribute was silently dropped and every
// axis label fell back to the browser default near-black — legible enough on
// the light surface to go unnoticed, invisible on the dark one. Wrap it back up.
export function axisColor() {
  const channels = token("--ink-muted");
  return channels ? `rgb(${channels})` : "#898781";
}
// --grid and --viz-surface stay hex precisely so charts can read them straight
// back (see the comment in index.css).
export function gridColor() {
  return token("--grid") || "#e1e0d9";
}
/** The card surface behind a chart — the colour of the 2px gap between fills. */
export function surfaceColor() {
  return token("--viz-surface") || "#ffffff";
}
