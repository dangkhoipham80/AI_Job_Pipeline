import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Globe,
  Mail,
  Shield,
  User,
} from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { STATUS_INFO, FUNNEL_STEPS } from "@/lib/statuses";
import { StatusPill } from "@/components/StatusPill";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { JobStatus } from "@/types";

/**
 * Guide — what the nine statuses mean and how a job travels between them.
 *
 * Written against live counts rather than as a static wall of text: the point
 * of reading this page is usually "why is nothing happening?", and the answer
 * is almost always a number sitting in a column that is waiting on you.
 */
export function Guide({ version }: { version: number }) {
  const { data: stats } = useApi(() => api.stats(), [version]);
  const { data: apply } = useApi(() => api.applySettings(), [version]);
  const count = (s: JobStatus) => stats?.by_status?.[s] ?? 0;

  const waiting = (["DISCOVERED", "SHORTLISTED", "REVIEW", "APPROVED"] as JobStatus[])
    .map((s) => ({ status: s, n: count(s) }))
    .filter((x) => x.n > 0);

  return (
    <div className="animate-fade-up space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">How this works</h1>
        <p className="mt-0.5 text-sm text-ink-muted">
          A job moves through nine states. Six are the happy path; two are exits; one means
          something broke.
        </p>
      </div>

      {waiting.length > 0 && (
        <Card className="flex flex-wrap items-center gap-x-3 gap-y-2 border-accent/40 bg-accent/8 px-4 py-3 text-sm">
          <User size={15} className="shrink-0 text-accent" />
          <span className="font-medium">Waiting on you right now:</span>
          {waiting.map(({ status, n }) => (
            <Link key={status} to={`/jobs?status=${status}`} className="hover:opacity-80">
              <StatusPill status={status} /> <span className="tabular-nums">×{n}</span>
            </Link>
          ))}
        </Card>
      )}

      {/* The funnel, in order */}
      <Card>
        <CardHeader>
          <CardTitle>The funnel</CardTitle>
          <span className="text-[11px] text-ink-muted">top to bottom, one job at a time</span>
        </CardHeader>
        <CardBody className="pt-4">
          <ol className="flex flex-col">
            {FUNNEL_STEPS.map((status, i) => (
              <Step
                key={status}
                status={status}
                n={count(status)}
                last={i === FUNNEL_STEPS.length - 1}
              />
            ))}
          </ol>

          <div className="mt-5 border-t pt-4">
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-muted">
              Exits
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {(["SKIPPED", "FAILED"] as JobStatus[]).map((status) => (
                <div key={status} className="rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <StatusPill status={status} />
                    <span className="font-mono text-[11px] tabular-nums text-ink-muted">
                      {count(status)}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink/90">
                    {STATUS_INFO[status].meaning}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* The two decisions that actually cost something */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Why shortlist at all?</CardTitle>
          </CardHeader>
          <CardBody className="space-y-2.5 pt-3 text-sm leading-relaxed text-ink/90">
            <p>
              Tailoring costs a Claude call and a LaTeX build — about a minute and real API
              budget per job. A crawl can turn up dozens overnight, and most of them you can
              rule out from the title alone.
            </p>
            <p>
              <span className="font-medium">Shortlist is that filter.</span> You pick the handful
              worth a CV of their own; the agent only does expensive work on those. Everything
              else you Skip, and a re-crawl won't push it back in your face.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <Shield size={15} className="mr-1.5 inline text-accent" />
              What the agent cannot do
            </CardTitle>
          </CardHeader>
          <CardBody className="space-y-2.5 pt-3 text-sm leading-relaxed text-ink/90">
            <p>
              It cannot add a skill you don't have. The tailor plan addresses your master CV{" "}
              <span className="font-medium">by index</span> — it may reorder, trim or hide what is
              already there, and the only free text it writes is the summary, which is checked
              word by word against your CV's vocabulary.
            </p>
            <p>
              A gap gets named in one place only: the "happy to learn X" line of the cover letter.
              Claiming X is not something the format can express.
            </p>
          </CardBody>
        </Card>
      </div>

      {/* Apply channels — the part with outside-world consequences */}
      <Card>
        <CardHeader>
          <CardTitle>What "Apply" does depends on the channel</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3 pt-3">
          <Channel
            icon={Mail}
            name="email"
            tone={apply?.email_enabled && !apply?.email_dry_run ? "live" : "held"}
            status={
              apply
                ? apply.email_blocker
                  ? `Held: ${apply.email_blocker}`
                  : "Live — Apply sends the message"
                : "…"
            }
          >
            The only channel that sends by itself. Three independent gates guard it —{" "}
            <code className="rounded bg-surface-2 px-1 text-[12px]">enabled</code>,{" "}
            <code className="rounded bg-surface-2 px-1 text-[12px]">dry_run</code>,{" "}
            <code className="rounded bg-surface-2 px-1 text-[12px]">test_recipient</code> — and all
            three ship closed. While any gate holds, Apply builds the mail and shows it to you
            without opening a socket, and the job stays{" "}
            <StatusPill status="APPROVED" className="align-middle" />.
          </Channel>

          <Channel icon={Globe} name="portal" tone="held" status="Always your hand on the button">
            You get a handoff package: the URL, the tailored PDF, and every field ready to paste.
            Optionally the browser opens pre-filled — but nothing is ever submitted for you. When
            you've sent it, hit <span className="font-medium">Confirm submitted</span>.
          </Channel>

          <Channel icon={ArrowRight} name="external" tone="held" status="LinkedIn lands here">
            The posting lives somewhere JobPilot won't touch. You apply on the site; JobPilot just
            records that you did.
          </Channel>
        </CardBody>
      </Card>

      {/* LinkedIn caveat — the one that surprises people */}
      <Card className="border-accent/30">
        <CardBody className="flex items-start gap-3 py-4 text-sm leading-relaxed">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-accent" />
          <div className="space-y-2">
            <p>
              <span className="font-medium">LinkedIn jobs arrive without a description.</span>{" "}
              They come from Job Alert emails in your own inbox — LinkedIn's robots.txt forbids
              crawling the job pages, so JobPilot never fetches them. The alert carries the title,
              company and location, and nothing else.
            </p>
            <p className="text-ink-muted">
              Those jobs are flagged on their detail page. Open the posting, paste the description
              in, and then tailor — otherwise the agent is writing against an empty brief.
            </p>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

const ACTOR_ICON = { you: User, agent: Bot, done: CheckCircle2 } as const;
const ACTOR_LABEL = { you: "your move", agent: "agent working", done: "finished" } as const;

function Step({ status, n, last }: { status: JobStatus; n: number; last: boolean }) {
  const info = STATUS_INFO[status];
  const Icon = ACTOR_ICON[info.actor];
  return (
    <li className="flex gap-3">
      {/* Rail: the dot marks the step, the line carries you to the next one. */}
      <div className="flex flex-col items-center">
        {/* Filled = your move, hollow = the agent's. Both must read clearly,
            or the rail looks broken where the agent is working. */}
        <span
          className={cn(
            "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border-2",
            info.actor === "you"
              ? "border-accent bg-accent"
              : "border-ink-muted/60 bg-surface",
          )}
        />
        {!last && <span className="my-1 w-px flex-1 bg-ink-muted/30" />}
      </div>

      <div className={cn("min-w-0 flex-1", last ? "pb-0" : "pb-5")}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={status} />
          <span className="font-mono text-[11px] tabular-nums text-ink-muted">{n}</span>
          <span
            className={cn(
              "inline-flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide",
              info.actor === "you" ? "text-accent" : "text-ink-muted",
            )}
          >
            <Icon size={12} /> {ACTOR_LABEL[info.actor]}
          </span>
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-ink/90">{info.meaning}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-ink-muted">{info.next}</p>
      </div>
    </li>
  );
}

function Channel({
  icon: Icon,
  name,
  status,
  tone,
  children,
}: {
  icon: typeof Mail;
  name: string;
  status: string;
  tone: "live" | "held";
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Icon size={15} className={tone === "live" ? "text-good" : "text-ink-muted"} />
        <span className="font-mono text-sm font-medium">{name}</span>
        <span
          className={cn(
            "rounded-md border px-1.5 py-0.5 text-[11px]",
            tone === "live"
              ? "border-good/40 bg-good/10 text-good"
              : "border-ink/15 text-ink-muted",
          )}
        >
          {status}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-ink/90">{children}</p>
    </div>
  );
}
