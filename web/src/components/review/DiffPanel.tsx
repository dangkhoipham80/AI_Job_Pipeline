import { ArrowRight, Eye, EyeOff, MoveVertical, PenLine, Scissors } from "lucide-react";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { CvDiff, DiffStatus, TailorChange } from "@/types";

/**
 * The tailor mostly *moves* content, so a line diff would mark every bullet as
 * changed. This renders the structural diff from jobpilot/tailor/diff.py: what
 * moved, what was trimmed, what was rewritten — the questions a reviewer has.
 */

const STATUS: Record<DiffStatus, { label: string; icon: typeof PenLine; className: string }> = {
  rewritten: { label: "Rewritten", icon: PenLine, className: "text-accent border-accent/40 bg-accent/10" },
  trimmed: { label: "Trimmed", icon: Scissors, className: "text-critical border-critical/40 bg-critical/8" },
  hidden: { label: "Hidden", icon: EyeOff, className: "text-ink-muted border-border bg-surface-2" },
  reordered: { label: "Reordered", icon: MoveVertical, className: "text-good border-good/40 bg-good/8" },
  unchanged: { label: "Unchanged", icon: Eye, className: "text-ink-muted border-border" },
};

export function DiffPanel({ diff, changes }: { diff: CvDiff; changes: TailorChange[] }) {
  const touched = diff.sections.filter((s) => s.status !== "unchanged");
  const untouched = diff.sections.filter((s) => s.status === "unchanged");

  return (
    <Card>
      <CardHeader>
        <CardTitle>What changed</CardTitle>
        <span className="font-mono text-[11px] text-ink-muted">
          {touched.length} of {diff.sections.length} sections
        </span>
      </CardHeader>
      <CardBody className="flex flex-col gap-4 pt-3">
        {changes.length > 0 && (
          <ul className="flex flex-col gap-2">
            {changes.map((c, i) => (
              <li key={i} className="flex gap-2 text-sm leading-relaxed">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                <span>
                  <span className="font-medium">{c.what}</span>
                  <span className="text-ink-muted"> — {c.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        )}

        {diff.order_changed && (
          <div className="rounded-lg border bg-surface-2/60 px-3 py-2 text-xs">
            <span className="font-semibold uppercase tracking-[0.1em] text-ink-muted">
              Section order
            </span>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono">
              {diff.order_after.map((key, i) => (
                <span key={key} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight size={11} className="text-ink-muted/60" />}
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5",
                      diff.order_before[i] === key ? "text-ink-muted" : "bg-accent/12 text-ink",
                    )}
                  >
                    {key}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2">
          {touched.map((section) => {
            const meta = STATUS[section.status];
            const Icon = meta.icon;
            return (
              <div key={section.key} className="rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
                      meta.className,
                    )}
                  >
                    <Icon size={11} /> {meta.label}
                  </span>
                  <span className="text-sm font-medium">{section.title}</span>
                </div>

                {section.before !== null && section.after !== null ? (
                  <div className="mt-2 grid gap-2 text-[13px] leading-relaxed sm:grid-cols-2">
                    <p className="rounded-md border bg-surface-2/60 p-2 text-ink-muted line-through decoration-critical/50">
                      {section.before}
                    </p>
                    <p className="rounded-md border border-accent/30 bg-accent/6 p-2">
                      {section.after}
                    </p>
                  </div>
                ) : (
                  section.notes.length > 0 && (
                    <ul className="mt-1.5 flex flex-col gap-1 pl-1 text-xs text-ink-muted">
                      {section.notes.map((note, i) => (
                        <li key={i}>· {note}</li>
                      ))}
                    </ul>
                  )
                )}
              </div>
            );
          })}
        </div>

        {untouched.length > 0 && (
          <p className="text-xs text-ink-muted">
            Unchanged: {untouched.map((s) => s.title).join(", ")}
          </p>
        )}
      </CardBody>
    </Card>
  );
}
