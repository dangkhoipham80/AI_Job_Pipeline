import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Building2, Check, ExternalLink, MapPin, Sparkles, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import type { JobStatus } from "@/types";
import { relativeTime, titleCase } from "@/lib/format";
import { StatusPill } from "@/components/StatusPill";
import { MatchMeter } from "@/components/MatchMeter";
import { FreshBeacon } from "@/components/FreshBeacon";
import { sourceColor } from "@/components/charts/palette";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";

const EARLY = new Set<JobStatus>(["DISCOVERED", "SHORTLISTED", "SKIPPED"]);
// Statuses from which the CV Review page is worth opening (matches
// tailor/service.py TAILORABLE, plus APPROVED so you can re-read what you sent).
const TAILORABLE = new Set<JobStatus>(["SHORTLISTED", "TAILORING", "REVIEW", "APPROVED", "FAILED"]);

export function JobDetail({ version }: { version: number }) {
  const { id = "" } = useParams();
  const [pending, setPending] = useState(false);
  const { data: job, loading, error, refetch } = useApi(() => api.job(id), [id, version]);

  async function act(action: "shortlist" | "skip") {
    setPending(true);
    try {
      await api[action](id);
      await refetch();
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="animate-fade-up space-y-4">
      <Link
        to="/jobs"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
      >
        <ArrowLeft size={15} /> Back to jobs
      </Link>

      {error ? (
        <Card className="p-6 text-sm text-ink-muted">
          <span className="font-medium text-critical">Couldn't load this job.</span> {error}
        </Card>
      ) : loading || !job ? (
        <Skeleton className="h-72 rounded-card" />
      ) : (
        <>
          <Card>
            <CardBody className="space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {job.is_fresh && <FreshBeacon withLabel />}
                    <StatusPill status={job.status} />
                  </div>
                  <h1 className="mt-2 font-display text-2xl font-semibold leading-tight tracking-tight">
                    {job.title}
                  </h1>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-muted">
                    <span className="inline-flex items-center gap-1.5">
                      <Building2 size={14} /> {job.company}
                    </span>
                    {job.location && (
                      <span className="inline-flex items-center gap-1.5">
                        <MapPin size={14} /> {job.location}
                      </span>
                    )}
                    {job.salary && (
                      <span className="inline-flex items-center gap-1.5">
                        <Wallet size={14} /> {job.salary}
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 font-mono text-xs text-ink-muted">
                    <span
                      className="mr-1 inline-block h-2 w-2 rounded-sm align-middle"
                      style={{ background: sourceColor(job.source) }}
                    />
                    {job.id} · posted {relativeTime(job.posted_at)}
                  </div>
                </div>

                <div className="flex shrink-0 flex-col items-end gap-3">
                  <MatchMeter score={job.match_score} />
                  <div className="flex items-center gap-1.5">
                    {EARLY.has(job.status) && job.status !== "SHORTLISTED" && (
                      <Button size="sm" onClick={() => act("shortlist")} disabled={pending}>
                        <Check size={14} /> Shortlist
                      </Button>
                    )}
                    {EARLY.has(job.status) && job.status !== "SKIPPED" && (
                      <Button size="sm" variant="ghost" onClick={() => act("skip")} disabled={pending}>
                        Skip
                      </Button>
                    )}
                    {TAILORABLE.has(job.status) && (
                      <Link to={`/jobs/${encodeURIComponent(job.id)}/review`}>
                        <Button size="sm" variant={job.status === "REVIEW" ? "primary" : "outline"}>
                          <Sparkles size={14} />
                          {job.status === "REVIEW" ? "Review CV" : "Tailor CV"}
                        </Button>
                      </Link>
                    )}
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium text-ink-muted hover:bg-surface-2 hover:text-ink"
                    >
                      <ExternalLink size={14} /> Original
                    </a>
                  </div>
                </div>
              </div>

              {job.skills.length > 0 && (
                <div className="flex flex-wrap gap-1.5 border-t pt-4">
                  {job.skills.map((skill) => (
                    <Badge key={skill} className="border-ink/10 text-ink-muted">
                      {skill}
                    </Badge>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Job description</CardTitle>
              {job.apply_channel && (
                <span className="text-xs text-ink-muted">
                  applies via {titleCase(job.apply_channel)}
                </span>
              )}
            </CardHeader>
            <CardBody>
              {job.description_md ? (
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink/90">
                  {job.description_md}
                </pre>
              ) : (
                <p className="text-sm text-ink-muted">No description was captured for this job.</p>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
