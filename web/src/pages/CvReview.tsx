import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  FileText,
  Loader2,
  PenSquare,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { MatchMeter } from "@/components/MatchMeter";
import { StatusPill } from "@/components/StatusPill";
import { DiffPanel } from "@/components/review/DiffPanel";
import { GapReport } from "@/components/review/GapReport";
import { Button, Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { JobDetail, ReviewData } from "@/types";

/**
 * CV Review (PLAN.md §5.6). The tailored PDF sits next to the diff so the user
 * can check the claim against the artifact, then Approve / Sửa / Bỏ. "Sửa" has
 * two doors: an instruction for the agent, or CV Studio for a manual edit.
 */
export function CvReview({ version }: { version: number }) {
  const { id = "" } = useParams();
  const job = useApi(() => api.job(id), [id, version]);
  const review = useApi(() => api.review(id), [id, version]);

  const [busy, setBusy] = useState<null | "tailor" | "edit" | "approve" | "reject" | "apply">(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  const tailored = (review.data?.version ?? 0) > 0;

  // Re-fetch the PDF whenever a new tailored version lands.
  useEffect(() => {
    if (!tailored) return;
    let created: string | null = null;
    api
      .tailoredPdfUrl(id)
      .then((url) => {
        created = url;
        setPdfUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return url;
        });
      })
      .catch(() => setPdfUrl(null));
    return () => {
      if (created) URL.revokeObjectURL(created);
    };
  }, [id, tailored, review.data?.version]);

  const run = useCallback(
    async (
      kind: "tailor" | "edit" | "approve" | "reject" | "apply",
      fn: () => Promise<unknown>,
    ) => {
      setBusy(kind);
      setError(null);
      try {
        await fn();
        await Promise.all([job.refetch(), review.refetch()]);
        if (kind === "edit") setInstruction("");
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Request failed");
      } finally {
        setBusy(null);
      }
    },
    [job, review],
  );

  if (job.error) {
    return (
      <Card className="p-6 text-sm">
        <span className="font-medium text-critical">Couldn't load this job.</span> {job.error}
      </Card>
    );
  }
  if (job.loading && !job.data) return <ReviewSkeleton />;

  const data = job.data as JobDetail;
  const r = review.data;

  return (
    <div className="animate-fade-up space-y-4">
      <Link
        to={`/jobs/${encodeURIComponent(id)}`}
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
      >
        <ArrowLeft size={15} /> Back to job
      </Link>

      <Header
        job={data}
        review={r}
        busy={busy}
        onTailor={() => run("tailor", () => api.tailor(id))}
        onApprove={() => run("approve", () => api.approve(id))}
        onReject={() => run("reject", () => api.reject(id))}
        onApply={() =>
          run("apply", async () => {
            const outcome = await api.applyJob(id);
            setApplied(`${outcome.result} — ${outcome.detail}`);
          })
        }
      />

      {applied && (
        <Card className="border-l-2 border-l-accent">
          <CardBody className="flex items-center justify-between gap-3 py-3 text-sm">
            <span>{applied}</span>
            <Link to="/applications" className="shrink-0 text-ink-muted hover:text-ink">
              Applications board →
            </Link>
          </CardBody>
        </Card>
      )}

      {error && (
        <Card className="flex items-start gap-2 border-critical/40 bg-critical/5 p-3 text-sm">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
          <span>{error}</span>
        </Card>
      )}

      {!tailored ? (
        <NotTailoredYet
          busy={busy === "tailor"}
          onTailor={() => run("tailor", () => api.tailor(id))}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Card className="xl:sticky xl:top-20 xl:self-start">
            <CardHeader className="items-center">
              <CardTitle>Tailored CV</CardTitle>
              <PageBadge pages={r?.pages ?? null} />
            </CardHeader>
            <CardBody className="pt-3">
              {pdfUrl ? (
                <iframe
                  title="Tailored CV"
                  src={`${pdfUrl}#toolbar=0&view=FitH`}
                  className="h-[820px] w-full rounded-lg border bg-white"
                />
              ) : (
                <div className="grid h-[820px] place-items-center rounded-lg border border-dashed text-sm text-ink-muted">
                  <span className="flex items-center gap-2">
                    <FileText size={18} className="opacity-60" /> PDF not available
                  </span>
                </div>
              )}
            </CardBody>
          </Card>

          <div className="flex min-w-0 flex-col gap-4">
            {r?.diff && r.plan && <DiffPanel diff={r.diff} changes={r.plan.changes} />}
            {r?.plan && <GapReport requirements={r.plan.requirements} />}
            <EditBox
              id={id}
              value={instruction}
              onChange={setInstruction}
              busy={busy === "edit"}
              round={r?.round ?? 0}
              onSubmit={() => run("edit", () => api.editCv(id, instruction))}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Header({
  job,
  review,
  busy,
  onTailor,
  onApprove,
  onReject,
  onApply,
}: {
  job: JobDetail;
  review: ReviewData | null;
  busy: string | null;
  onTailor: () => void;
  onApprove: () => void;
  onReject: () => void;
  onApply: () => void;
}) {
  const canApprove = job.status === "REVIEW";
  const canTailor = ["SHORTLISTED", "REVIEW", "FAILED"].includes(job.status);
  const canApply = ["APPROVED", "FAILED", "SUBMITTING"].includes(job.status);

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate font-display text-xl font-semibold tracking-tight">
              {job.title}
            </h1>
            <StatusPill status={job.status} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-ink-muted">
            <span>{job.company}</span>
            {review && review.version > 0 && (
              <span className="font-mono text-[11px]">
                v{review.version}
                {review.round > 0 && ` · edit round ${review.round}`}
              </span>
            )}
            <MatchMeter score={review?.match_score ?? job.match_score} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/cv/${encodeURIComponent(job.id)}`}>
            <Button variant="outline" size="sm" disabled={!review || review.version === 0}>
              <PenSquare size={14} /> Open in CV Studio
            </Button>
          </Link>
          {canTailor && (
            <Button variant="outline" size="sm" onClick={onTailor} disabled={!!busy}>
              {busy === "tailor" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {review && review.version > 0 ? "Re-tailor" : "Tailor"}
            </Button>
          )}
          <Button variant="danger" size="sm" onClick={onReject} disabled={!!busy}>
            <X size={14} /> Skip
          </Button>
          {canApply ? (
            <Button size="sm" onClick={onApply} disabled={!!busy}>
              {busy === "apply" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              Apply
            </Button>
          ) : (
            <Button size="sm" onClick={onApprove} disabled={!!busy || !canApprove}>
              {busy === "approve" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Check size={14} />
              )}
              Approve
            </Button>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function PageBadge({ pages }: { pages: number | null }) {
  if (pages === null) return null;
  return (
    <span
      className={cn(
        "rounded-md border px-2 py-0.5 font-mono text-[11px]",
        pages === 1 ? "border-good/40 text-good" : "border-critical/40 text-critical",
      )}
      title={pages === 1 ? "Fits on one page" : "A CV should fit on one page — hide a section"}
    >
      {pages} page{pages === 1 ? "" : "s"}
    </span>
  );
}

function NotTailoredYet({ busy, onTailor }: { busy: boolean; onTailor: () => void }) {
  return (
    <Card>
      <CardBody className="flex flex-col items-center gap-3 py-16 text-center">
        <Sparkles size={22} className="text-ink-muted opacity-60" />
        <p className="max-w-md text-sm leading-relaxed text-ink-muted">
          Not tailored yet. Tailoring reorders and trims your Master CV for this posting — it
          never adds a skill you don't have. Takes about a minute: a Claude call plus a LaTeX
          build.
        </p>
        <Button onClick={onTailor} disabled={busy}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          {busy ? "Tailoring…" : "Tailor for this job"}
        </Button>
      </CardBody>
    </Card>
  );
}

function EditBox({
  value,
  onChange,
  busy,
  round,
  onSubmit,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  busy: boolean;
  round: number;
  onSubmit: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ask for a change</CardTitle>
        {round > 0 && <span className="font-mono text-[11px] text-ink-muted">round {round}</span>}
      </CardHeader>
      <CardBody className="flex flex-col gap-2 pt-3">
        <textarea
          rows={2}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="e.g. shorten the summary, put Food Forum last, lead with Docker"
          className="w-full resize-none rounded-lg border bg-surface px-3 py-2 text-sm leading-relaxed text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-ink-muted">
            The agent re-plans within the same rules — it will refuse anything that would
            claim experience you don't have.
          </p>
          <Button size="sm" onClick={onSubmit} disabled={busy || !value.trim()}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <PenSquare size={14} />}
            {busy ? "Re-tailoring…" : "Send"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function ReviewSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 rounded-card" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Skeleton className="h-[600px] rounded-card" />
        <div className="space-y-4">
          <Skeleton className="h-56 rounded-card" />
          <Skeleton className="h-40 rounded-card" />
        </div>
      </div>
    </div>
  );
}
