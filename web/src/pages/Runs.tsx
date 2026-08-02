import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { clockTime, relativeTime } from "@/lib/format";
import { Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { CrawlSetup } from "@/components/CrawlSetup";
import { cn } from "@/lib/utils";
import type { CrawlRequest, RunRecord, Task, TaskStatus } from "@/types";

/**
 * Runs (PLAN.md §5.6). Two timescales on one page: tasks currently in the
 * queue, and the persisted history of everything that has run. Failures show
 * their cause here rather than only in a terminal.
 */

const STATUS: Record<TaskStatus, { icon: typeof Clock; className: string }> = {
  queued: { icon: Clock, className: "text-ink-muted" },
  running: { icon: Loader2, className: "text-accent animate-spin" },
  done: { icon: CheckCircle2, className: "text-good" },
  failed: { icon: XCircle, className: "text-critical" },
};

/** How an apply dispatch ended. "done" is about the task, not the application. */
const OUTCOME: Record<string, string> = {
  success: "text-good",
  dry_run: "text-ink-muted",
  awaiting_user: "text-accent",
  failed: "text-critical",
};

export function Runs({ version }: { version: number }) {
  const tasks = useApi(() => api.tasks(), [version]);
  const runs = useApi(() => api.runs(), [version]);
  const [busy, setBusy] = useState(false);

  const active = (tasks.data ?? []).filter((t) => t.status === "queued" || t.status === "running");

  // Errors surface inside the setup card, next to the choices that caused them.
  const crawl = useCallback(
    async (body: CrawlRequest) => {
      setBusy(true);
      try {
        await api.startCrawl(body);
        await tasks.refetch();
      } finally {
        setBusy(false);
      }
    },
    [tasks],
  );

  return (
    <div className="animate-fade-up space-y-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Runs</h1>
        <p className="text-sm text-ink-muted">
          What the agent is doing now, and everything it has done.
        </p>
      </div>

      <CrawlSetup
        version={version}
        busy={busy}
        blocked={active.length > 0}
        onCrawl={crawl}
      />

      <Card>
        <CardHeader>
          <CardTitle>Queue</CardTitle>
          <span className="font-mono text-[11px] text-ink-muted">
            {tasks.data?.length ?? 0} recent
          </span>
        </CardHeader>
        <CardBody className="pt-3">
          {tasks.loading && !tasks.data ? (
            <Skeleton className="h-20" />
          ) : !tasks.data?.length ? (
            <p className="text-sm text-ink-muted">
              Nothing queued. Hit “Crawl now” to look for jobs.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {tasks.data.map((task) => (
                <TaskRow key={task.id} task={task} />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
          <span className="font-mono text-[11px] text-ink-muted">{runs.data?.length ?? 0} runs</span>
        </CardHeader>
        <CardBody className="pt-3">
          {runs.loading && !runs.data ? (
            <Skeleton className="h-24" />
          ) : !runs.data?.length ? (
            <p className="text-sm text-ink-muted">No runs recorded yet.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {runs.data.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function TaskRow({ task }: { task: Task }) {
  const meta = STATUS[task.status];
  const Icon = meta.icon;
  const sites = task.result?.sites ?? [];

  return (
    <li className="rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <Icon size={15} className={cn("shrink-0", meta.className)} />
        <span className="font-medium">{task.label}</span>
        <span className="font-mono text-[11px] text-ink-muted">{task.kind}</span>
        <span className="ml-auto text-xs text-ink-muted">
          {relativeTime(task.finished_at ?? task.started_at ?? task.created_at)}
        </span>
      </div>

      {task.progress && task.status === "running" && (
        <p className="mt-1 pl-6 text-xs text-ink-muted">{task.progress}</p>
      )}
      {/* A finished apply task is not the same as a sent application: the
          dispatch ran, and `result` says whether anything actually left. */}
      {task.status === "done" && task.result.result && (
        <p className="mt-1 pl-6 text-xs text-ink-muted">
          <span className={cn("font-medium", OUTCOME[task.result.result] ?? "text-ink")}>
            {task.result.result.replace("_", " ")}
          </span>
          {task.result.detail ? ` — ${task.result.detail}` : ""}
        </p>
      )}
      {task.status === "done" && task.result.version !== undefined && (
        <p className="mt-1 pl-6 text-xs text-ink-muted">
          v{task.result.version} · match{" "}
          {Math.round((task.result.match_score ?? 0) * 100)}% · {task.result.pages ?? "?"} page
          {task.result.pages === 1 ? "" : "s"}
        </p>
      )}
      {task.error && (
        <p
          className={cn(
            "mt-2 rounded-md border px-2 py-1 font-mono text-[11px] leading-relaxed",
            task.error_kind === "GuardrailViolation"
              ? "border-critical bg-critical/10 text-critical"
              : "border-critical/30 bg-critical/5 text-critical",
          )}
        >
          {task.error_kind === "GuardrailViolation" && <strong>guardrail · </strong>}
          {task.error}
        </p>
      )}

      {sites.length > 0 && (
        <table className="mt-2 w-full text-xs">
          <thead className="text-ink-muted">
            <tr className="text-left">
              <th className="font-medium">source</th>
              <th className="font-medium tabular-nums">new</th>
              <th className="font-medium tabular-nums">updated</th>
              <th className="font-medium tabular-nums">dup</th>
              <th className="font-medium tabular-nums">fresh</th>
            </tr>
          </thead>
          <tbody>
            {sites.map((site) => (
              <tr key={site.source} className={cn(!site.ok && "text-critical")}>
                <td className="py-0.5">{site.source}</td>
                {site.ok ? (
                  <>
                    <td className="tabular-nums">{site.inserted}</td>
                    <td className="tabular-nums">{site.updated}</td>
                    <td className="tabular-nums">{site.duplicates}</td>
                    <td className="tabular-nums">{site.fresh}</td>
                  </>
                ) : (
                  <td colSpan={4} className="truncate py-0.5" title={site.error ?? ""}>
                    {site.error}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

/**
 * A run's stats as one readable line.
 *
 * The blob is nested — `sites` maps each source to its own counters — so
 * stringifying the top level gave `sites=[object Object]`, which is worse than
 * showing nothing. This names the sources instead, since "which site actually
 * worked" is the question a run history exists to answer.
 */
function summarise(stats: Record<string, unknown> | undefined): string {
  if (!stats) return "";
  const parts: string[] = [];
  if (typeof stats.query === "string" && stats.query) parts.push(`"${stats.query}"`);

  const sites = stats.sites as Record<string, { ok?: boolean; inserted?: number }> | undefined;
  if (sites && typeof sites === "object") {
    parts.push(
      ...Object.entries(sites).map(([name, s]) =>
        s?.ok === false ? `${name}: failed` : `${name}: +${s?.inserted ?? 0}`,
      ),
    );
  }

  for (const [k, v] of Object.entries(stats)) {
    if (k === "ok" || k === "query" || k === "sites" || v === null) continue;
    if (typeof v === "object") continue; // nested; already unpacked or not useful inline
    parts.push(`${k}=${String(v)}`);
  }
  return parts.join("  ·  ");
}

function RunRow({ run }: { run: RunRecord }) {
  const ok = run.stats?.ok;
  const failed = ok === false;
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm">
      <span className="font-mono text-[11px] text-ink-muted">#{run.id}</span>
      <span className="font-medium">{run.kind}</span>
      {failed && <XCircle size={13} className="text-critical" />}
      {/* The whole point of the run history: what did *this* crawl turn up. */}
      {run.job_count > 0 && (
        <Link
          to={`/jobs?run=${run.id}`}
          className="rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[11px] text-accent hover:bg-accent/20"
        >
          {run.job_count} job{run.job_count === 1 ? "" : "s"} →
        </Link>
      )}
      <span
        className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-muted"
        title={summarise(run.stats)}
      >
        {summarise(run.stats)}
      </span>
      {/* Absolute clock time, not "3h ago": "which of today's crawls was that?"
          is a question relative time cannot answer. */}
      <span
        className="whitespace-nowrap font-mono text-xs text-ink-muted"
        title={relativeTime(run.finished_at ?? run.started_at)}
      >
        {clockTime(run.started_at)}
      </span>
    </li>
  );
}
