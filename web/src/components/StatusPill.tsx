import type { JobStatus } from "@/types";
import { statusTooltip } from "@/lib/statuses";
import { cn } from "@/lib/utils";

// Status is state, not a data series — a reserved, labeled vocabulary. Color
// never carries meaning alone; the text label always shows.
//
// The mid-stage hues are literal hex rather than theme tokens, so they need an
// explicit dark variant: a colour picked for contrast against white paper is
// unreadable on a near-black surface.
const STYLES: Record<JobStatus, string> = {
  DISCOVERED: "border-ink/15 text-ink-muted",
  SHORTLISTED: "border-accent/40 text-accent bg-accent/10",
  TAILORING: "border-[#4a3aa7]/40 text-[#5b4bd0] bg-[#4a3aa7]/10 dark:text-[#a99cf0]",
  REVIEW: "border-[#2a78d6]/40 text-[#2a78d6] bg-[#2a78d6]/10 dark:text-[#79b0f0]",
  APPROVED: "border-[#1baf7a]/40 text-[#128a5f] bg-[#1baf7a]/10 dark:text-[#45d3a0]",
  SUBMITTING: "border-[#eda100]/50 text-[#a97600] bg-[#eda100]/10 dark:text-[#e8bb4e]",
  SUBMITTED: "border-good/40 text-good bg-good/10",
  FAILED: "border-critical/40 text-critical bg-critical/10",
  SKIPPED: "border-ink/10 text-ink-muted/70 line-through",
};

export function StatusPill({ status, className }: { status: JobStatus; className?: string }) {
  return (
    <span
      // Nine one-word states carry a lot of meaning; hovering explains what the
      // word means and whose move it is, without a trip to the Guide.
      title={statusTooltip(status)}
      className={cn(
        "inline-flex cursor-help items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        STYLES[status],
        className,
      )}
    >
      {status.toLowerCase()}
    </span>
  );
}
