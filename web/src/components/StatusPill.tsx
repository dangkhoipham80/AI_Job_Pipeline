import type { JobStatus } from "@/types";
import { cn } from "@/lib/utils";

// Status is state, not a data series — a reserved, labeled vocabulary. Color
// never carries meaning alone; the text label always shows.
const STYLES: Record<JobStatus, string> = {
  DISCOVERED: "border-ink/15 text-ink-muted",
  SHORTLISTED: "border-accent/40 text-accent bg-accent/10",
  TAILORING: "border-[#4a3aa7]/40 text-[#5b4bd0] bg-[#4a3aa7]/10",
  REVIEW: "border-[#2a78d6]/40 text-[#2a78d6] bg-[#2a78d6]/10",
  APPROVED: "border-[#1baf7a]/40 text-[#128a5f] bg-[#1baf7a]/10",
  SUBMITTING: "border-[#eda100]/50 text-[#a97600] bg-[#eda100]/10",
  SUBMITTED: "border-good/40 text-good bg-good/10",
  FAILED: "border-critical/40 text-critical bg-critical/10",
  SKIPPED: "border-ink/10 text-ink-muted/70 line-through",
};

export function StatusPill({ status, className }: { status: JobStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        STYLES[status],
        className,
      )}
    >
      {status.toLowerCase()}
    </span>
  );
}
