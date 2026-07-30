import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// A stat tile: hero figure + label, optional accent + trailing note. Hero uses
// proportional figures (per dataviz); no decorative chart.
export function StatCard({
  label,
  value,
  note,
  icon,
  accent = false,
  className,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  icon?: ReactNode;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("rounded-card border bg-surface p-4", accent && "border-accent/40", className)}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</span>
        {icon && <span className={cn("text-ink-muted", accent && "text-accent")}>{icon}</span>}
      </div>
      <div className="mt-2 font-display text-3xl font-semibold leading-none text-ink">{value}</div>
      {note && <div className="mt-1.5 text-xs text-ink-muted">{note}</div>}
    </div>
  );
}
