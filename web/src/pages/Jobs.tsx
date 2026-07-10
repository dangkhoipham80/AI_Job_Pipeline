import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, ExternalLink, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import type { Job, JobStatus, JobsQuery } from "@/types";
import { relativeTime, titleCase } from "@/lib/format";
import { StatusPill } from "@/components/StatusPill";
import { MatchMeter } from "@/components/MatchMeter";
import { FreshBeacon } from "@/components/FreshBeacon";
import { sourceColor } from "@/components/charts/palette";
import { Button, Card, Input, Select, Skeleton } from "@/components/ui";

const SOURCES = ["itviec", "topcv", "vietnamworks", "topdev"];
const LEVELS = ["intern", "fresher", "junior", "middle", "senior"];
const STATUSES: JobStatus[] = [
  "DISCOVERED",
  "SHORTLISTED",
  "TAILORING",
  "REVIEW",
  "APPROVED",
  "SUBMITTED",
  "FAILED",
  "SKIPPED",
];

const EARLY = new Set<JobStatus>(["DISCOVERED", "SHORTLISTED", "SKIPPED"]);

export function Jobs({ version }: { version: number }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [fresh, setFresh] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  const query: JobsQuery = useMemo(
    () => ({
      q: q || undefined,
      source: source || undefined,
      level: level || undefined,
      status: (status || undefined) as JobStatus | undefined,
      fresh: fresh || undefined,
      limit: 200,
    }),
    [q, source, level, status, fresh],
  );

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

  const hasFilters = q || source || level || status || fresh;

  return (
    <div className="animate-fade-up space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            {jobs ? `${jobs.length} shown` : "Loading…"} · newest postings first
          </p>
        </div>
      </div>

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
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </Select>
        <Select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">All levels</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {titleCase(l)}
            </option>
          ))}
        </Select>
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s.toLowerCase())}
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
              setStatus("");
              setFresh(false);
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
        <MatchMeter score={job.match_score} />
      </td>
      <td className="px-2 py-3">
        <StatusPill status={job.status} />
      </td>
      <td className="whitespace-nowrap px-2 py-3 font-mono text-xs tabular-nums text-ink-muted">
        {relativeTime(job.posted_at)}
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
