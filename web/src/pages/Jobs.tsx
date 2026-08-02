import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, ExternalLink, History, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import type { Job, JobStatus, JobsQuery } from "@/types";
import { relativeTime, titleCase } from "@/lib/format";
import { StatusPill } from "@/components/StatusPill";
import { MatchMeter, QualityFlags } from "@/components/MatchMeter";
import { FreshBeacon } from "@/components/FreshBeacon";
import { sourceColor } from "@/components/charts/palette";
import { Button, Card, Input, Select, Skeleton } from "@/components/ui";
import { AddJobForm } from "@/components/AddJobForm";

const EARLY = new Set<JobStatus>(["DISCOVERED", "SHORTLISTED", "SKIPPED"]);

/** Crawl-time windows. `hours: null` means "any time". */
const WINDOWS: { key: string; label: string; hours: number | null }[] = [
  { key: "", label: "Any time", hours: null },
  { key: "24h", label: "Last 24h", hours: 24 },
  { key: "7d", label: "Last 7 days", hours: 24 * 7 },
  { key: "30d", label: "Last 30 days", hours: 24 * 30 },
];

export function Jobs({ version }: { version: number }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [level, setLevel] = useState("");
  const [fresh, setFresh] = useState(false);
  const [win, setWin] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  // `run` and `status` live in the URL, not in state: both are arrived at from
  // somewhere else — the Runs page ("what did this crawl find?") and the Guide
  // ("3 jobs are waiting on you") — and a link has to be able to say which.
  const [params, setParams] = useSearchParams();
  const runId = Number(params.get("run")) || undefined;
  const status = params.get("status") ?? "";

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  // Filter options are whatever is actually in the database, so the list can
  // never drift out of step with the sources and levels really being crawled.
  const { data: stats } = useApi(() => api.stats(), [version]);
  const sources = Object.keys(stats?.by_source ?? {}).sort();
  const levels = Object.keys(stats?.by_level ?? {}).sort();
  // The API seeds by_status with every JobStatus, so this stays complete even
  // for statuses no job currently has. The URL's own status is folded in
  // regardless: while stats is still loading the <select> would otherwise show
  // blank while the filter *is* applied, which reads as a broken link.
  const statuses = Object.keys(stats?.by_status ?? {}) as JobStatus[];
  if (status && !statuses.includes(status as JobStatus)) statuses.unshift(status as JobStatus);

  const query: JobsQuery = useMemo(() => {
    const hours = WINDOWS.find((w) => w.key === win)?.hours ?? null;
    return {
      q: q || undefined,
      source: source || undefined,
      level: level || undefined,
      status: (status || undefined) as JobStatus | undefined,
      fresh: fresh || undefined,
      run_id: runId,
      crawled_after: hours ? new Date(Date.now() - hours * 3600 * 1000).toISOString() : undefined,
      // Filtering by crawl time only reads right if the list is sorted that way.
      order: win || runId ? "crawled" : "posted",
      limit: 200,
    };
  }, [q, source, level, status, fresh, win, runId]);

  const { data: jobs, loading, error, refetch } = useApi(() => api.jobs(query), [query, version]);

  async function act(id: string, action: "shortlist" | "skip") {
    setPending(id);
    try {
      await api[action](id);
      await refetch();
    } finally {
      setPending(null);
    }
  }

  const hasFilters = q || source || level || status || fresh || win || runId;

  return (
    <div className="animate-fade-up space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            {jobs ? `${jobs.length} shown` : "Loading…"} ·{" "}
            {query.order === "crawled" ? "most recently crawled first" : "newest postings first"}
          </p>
        </div>
        <AddJobForm onCreated={() => refetch()} />
      </div>

      {runId && (
        <Card className="flex items-center gap-2 px-3 py-2 text-sm">
          <History size={14} className="text-accent" />
          <span>
            Showing only what <span className="font-medium">crawl #{runId}</span> discovered.
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => setParams({}, { replace: true })}
          >
            <X size={14} /> Show all
          </Button>
        </Card>
      )}

      {/* Filter bar */}
      <Card className="flex flex-wrap items-center gap-2 p-3">
        <div className="relative min-w-[200px] flex-1">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title or company"
            className="pl-8"
          />
        </div>
        <Select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </Select>
        <Select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">All levels</option>
          {levels.map((l) => (
            <option key={l} value={l}>
              {titleCase(l)}
            </option>
          ))}
        </Select>
        <Select value={status} onChange={(e) => setParam("status", e.target.value)}>
          <option value="">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {titleCase(s.toLowerCase())}
            </option>
          ))}
        </Select>
        <Select value={win} onChange={(e) => setWin(e.target.value)} title="When it was crawled">
          {WINDOWS.map((w) => (
            <option key={w.key} value={w.key}>
              {w.label}
            </option>
          ))}
        </Select>
        <button
          onClick={() => setFresh((f) => !f)}
          className={
            "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors " +
            (fresh ? "border-accent bg-accent/10 text-accent" : "text-ink-muted hover:bg-surface-2")
          }
        >
          <FreshBeacon /> Fresh
        </button>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQ("");
              setSource("");
              setLevel("");
              setFresh(false);
              setWin("");
              setParams({}, { replace: true });
            }}
          >
            <X size={14} /> Clear
          </Button>
        )}
      </Card>

      {error ? (
        <Card className="p-6 text-sm text-ink-muted">
          <span className="font-medium text-critical">Couldn't load jobs.</span> {error}
        </Card>
      ) : loading || !jobs ? (
        <TableSkeleton />
      ) : jobs.length === 0 ? (
        <EmptyState hasFilters={!!hasFilters} />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-2 py-2.5 font-medium">Source</th>
                <th className="px-2 py-2.5 font-medium">Match</th>
                <th className="px-2 py-2.5 font-medium">Status</th>
                <th className="px-2 py-2.5 font-medium">Posted</th>
                <th className="px-2 py-2.5 font-medium">Crawled</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <Row key={job.id} job={job} pending={pending === job.id} onAct={act} />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function Row({
  job,
  pending,
  onAct,
}: {
  job: Job;
  pending: boolean;
  onAct: (id: string, action: "shortlist" | "skip") => void;
}) {
  const isFresh =
    !!job.posted_at && Date.now() - new Date(job.posted_at).getTime() < 48 * 3600 * 1000;
  return (
    <tr className="border-b last:border-0 hover:bg-surface-2/60">
      <td className="max-w-[320px] px-4 py-3">
        <Link to={`/jobs/${encodeURIComponent(job.id)}`} className="group block">
          <div className="flex items-center gap-1.5">
            {isFresh && <FreshBeacon />}
            <span className="truncate font-medium text-ink group-hover:text-accent">{job.title}</span>
          </div>
          <div className="truncate text-xs text-ink-muted">
            {job.company}
            {job.location ? ` · ${job.location}` : ""}
            {job.salary ? ` · ${job.salary}` : ""}
          </div>
        </Link>
      </td>
      <td className="px-2 py-3">
        <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="h-2 w-2 rounded-sm" style={{ background: sourceColor(job.source) }} />
          {titleCase(job.source)}
        </span>
      </td>
      <td className="px-2 py-3">
        <MatchMeter score={job.match_score} quality={job.quality} />
        <QualityFlags quality={job.quality} className="mt-1" />
      </td>
      <td className="px-2 py-3">
        <StatusPill status={job.status} />
      </td>
      <td className="whitespace-nowrap px-2 py-3 font-mono text-xs tabular-nums text-ink-muted">
        {relativeTime(job.posted_at)}
      </td>
      <td className="whitespace-nowrap px-2 py-3 font-mono text-xs tabular-nums text-ink-muted">
        {job.run_id ? (
          <Link
            to={`/jobs?run=${job.run_id}`}
            className="hover:text-accent"
            title={`Only jobs from crawl #${job.run_id}`}
          >
            {relativeTime(job.crawled_at)}
          </Link>
        ) : (
          <span title="Added by hand">{relativeTime(job.crawled_at)}</span>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-1">
          {EARLY.has(job.status) && job.status !== "SHORTLISTED" && (
            <Button size="sm" onClick={() => onAct(job.id, "shortlist")} disabled={pending}>
              <Check size={14} /> Shortlist
            </Button>
          )}
          {EARLY.has(job.status) && job.status !== "SKIPPED" && (
            <Button size="sm" variant="ghost" onClick={() => onAct(job.id, "skip")} disabled={pending}>
              Skip
            </Button>
          )}
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
            title="Open original posting"
          >
            <ExternalLink size={14} />
          </a>
        </div>
      </td>
    </tr>
  );
}

function TableSkeleton() {
  return (
    <Card className="divide-y p-0">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 p-4">
          <Skeleton className="h-8 flex-1" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </Card>
  );
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <Card className="grid place-items-center gap-1 py-16 text-center">
      <p className="font-medium text-ink">{hasFilters ? "No jobs match these filters." : "No jobs yet."}</p>
      <p className="text-sm text-ink-muted">
        {hasFilters
          ? "Try clearing a filter."
          : "Run a crawl: python -m jobpilot.cli crawl"}
      </p>
    </Card>
  );
}
