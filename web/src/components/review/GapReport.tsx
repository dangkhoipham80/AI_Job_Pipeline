import { AlertTriangle, Check, Minus } from "lucide-react";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { RequirementStatus, TailorRequirement } from "@/types";

/**
 * The honest half of the review. Missing requirements are shown first and never
 * softened — SKILL.md §0 forbids putting them on the CV, so the only useful
 * thing to do with them is tell the user plainly.
 */

const STATUS: Record<RequirementStatus, { icon: typeof Check; className: string; label: string }> = {
  HAVE: { icon: Check, className: "text-good", label: "in your CV" },
  PARTIAL: { icon: Minus, className: "text-accent", label: "related experience" },
  MISSING: { icon: AlertTriangle, className: "text-critical", label: "not in your CV" },
};

const ORDER: RequirementStatus[] = ["MISSING", "PARTIAL", "HAVE"];

export function GapReport({ requirements }: { requirements: TailorRequirement[] }) {
  const sorted = [...requirements].sort(
    (a, b) =>
      ORDER.indexOf(a.status) - ORDER.indexOf(b.status) ||
      Number(b.kind === "must_have") - Number(a.kind === "must_have"),
  );
  const missing = requirements.filter((r) => r.status === "MISSING");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Requirements</CardTitle>
        {missing.length > 0 ? (
          <span className="font-mono text-[11px] text-critical">{missing.length} gap{missing.length === 1 ? "" : "s"}</span>
        ) : (
          <span className="font-mono text-[11px] text-good">no gaps</span>
        )}
      </CardHeader>
      <CardBody className="pt-3">
        {sorted.length === 0 ? (
          <p className="text-sm text-ink-muted">No requirements were extracted from this posting.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {sorted.map((req, i) => {
              const meta = STATUS[req.status];
              const Icon = meta.icon;
              return (
                <li key={i} className="flex items-start gap-2 rounded-md px-1 py-1 text-sm">
                  <Icon size={14} className={cn("mt-0.5 shrink-0", meta.className)} />
                  <div className="min-w-0 flex-1">
                    <span className={cn(req.status === "MISSING" && "font-medium")}>{req.text}</span>
                    {req.kind === "must_have" && (
                      <span className="ml-1.5 rounded border border-ink-muted/30 px-1 py-px text-[10px] uppercase tracking-wide text-ink-muted">
                        must
                      </span>
                    )}
                    <div className="text-xs text-ink-muted">
                      {meta.label}
                      {req.evidence && ` · ${req.evidence}`}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {missing.length > 0 && (
          <p className="mt-3 rounded-lg border border-critical/30 bg-critical/6 px-3 py-2 text-xs leading-relaxed text-ink-muted">
            These were deliberately left off the CV — claiming them would be untrue. Decide
            whether to learn them, mention willingness to learn in the cover letter, or skip
            this job.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
