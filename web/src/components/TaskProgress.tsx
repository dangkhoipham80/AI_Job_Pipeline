import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";
import { Card, CardBody } from "@/components/ui";
import { isActive } from "@/hooks/useTask";
import { cn } from "@/lib/utils";
import type { Task } from "@/types";

/**
 * The live state of one background task (PLAN.md §5.5).
 *
 * Tailoring and applying used to block the request, so a spinner said all there
 * was to say. Now that they run on the queue there are real stages worth
 * naming — "planning against the JD" and "building the PDF" fail for completely
 * different reasons, and knowing which one you're in is the difference between
 * waiting and debugging.
 */
export function TaskProgress({ task, className }: { task: Task; className?: string }) {
  if (isActive(task)) {
    return (
      <Card className={cn("border-l-2 border-l-accent", className)}>
        <CardBody className="flex items-center gap-2.5 py-3 text-sm">
          <Loader2 size={15} className="shrink-0 animate-spin text-accent" />
          <span className="font-medium">{task.status === "queued" ? "Queued" : "Working"}</span>
          <span className="min-w-0 flex-1 truncate text-ink-muted">
            {task.progress || (task.status === "queued" ? "waiting for a free worker" : "…")}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-ink-muted">{task.kind}</span>
        </CardBody>
      </Card>
    );
  }

  if (task.status === "failed") return <TaskFailure task={task} className={className} />;
  return null;
}

/**
 * A guardrail violation is not a bug report, it's the system working: the agent
 * proposed a CV claiming something the Master CV doesn't support, and the plan
 * was thrown away before anything was written. It gets its own treatment so it
 * is never mistaken for a transient build failure worth retrying.
 */
function TaskFailure({ task, className }: { task: Task; className?: string }) {
  const guardrail = task.error_kind === "GuardrailViolation";
  const Icon = guardrail ? ShieldAlert : AlertTriangle;

  return (
    <Card className={cn("border-critical/40 bg-critical/5", className)}>
      <CardBody className="flex items-start gap-2.5 py-3 text-sm">
        <Icon size={16} className="mt-0.5 shrink-0 text-critical" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">
            {guardrail ? "Blocked: the plan claimed something unsupported" : "That didn't finish"}
          </p>
          <p className="break-words leading-relaxed text-ink-muted">{task.error}</p>
          {guardrail && (
            <p className="text-[12px] leading-relaxed text-ink-muted">
              Nothing was written to your CV. Add the experience to your Master CV if it's real,
              or try again — the agent re-plans from scratch.
            </p>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
