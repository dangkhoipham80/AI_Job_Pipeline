import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { clockTime, relativeTime } from "@/lib/format";
import { Button, Card, CardBody, CardHeader, CardTitle, Input, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { RunRecord, Task, TaskStatus } from "@/types";

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

export function Runs({ version }: { version: number }) {
  const tasks = useApi(() => api.tasks(), [version]);
  const runs = useApi(() => api.runs(), [version]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const crawl = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.startCrawl(query.trim() || undefined);
      await tasks.refetch();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the crawl");
    } finally {
      setBusy(false);
    }
  }, [query, tasks]);

  const active = (tasks.data ?? []).filter((t) => t.status === "queued" || t.status === "running");

  return (
    <div className="animate-fade-up space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="text-sm text-ink-muted">
            What the agent is doing now, and everything it has done.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="query (default: your stacks)"
            className="w-64"
          />
          <Button onClick={crawl} disabled={busy || active.length > 0}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            Crawl now
          </Button>
        </div>
      </div>

      {active.length > 0 && (
        <p className="text-xs text-ink-muted">
          One crawl at a time — a second would race the same sites and trip their rate limits.
        </p>
      )}
      {error && (
        <Card className="flex items-start gap-2 border-critical/40 bg-critical/5 p-3 text-sm">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
          <span>{error}</span>
        </Card>
      )}

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
      {task.error && (
        <p className="mt-2 rounded-md border border-critical/30 bg-critical/5 px-2 py-1 font-mono text-[11px] leading-relaxed text-critical">
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
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-muted">
        {Object.entries(run.stats ?? {})
          .filter(([k]) => k !== "ok")
          .map(([k, v]) => `${k}=${String(v)}`)
          .join("  ")}
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
