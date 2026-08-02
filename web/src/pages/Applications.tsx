import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  FileText,
  Loader2,
  Mail,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { FollowUps } from "@/components/FollowUps";
import { relativeTime } from "@/lib/format";
import { Badge, Button, Card, CardBody, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Application, ApplyResult, ApplySettings } from "@/types";

/**
 * Applications board (PLAN.md §5.6). Columns are what happened, not where the
 * job is in the funnel — "Prepared" exists precisely so a dry run is never read
 * as a send. The gate banner up top says which of the three email safeties are
 * currently open.
 */

const COLUMNS: { key: ApplyResult; title: string; hint: string; accent: string }[] = [
  {
    key: "dry_run",
    title: "Prepared",
    hint: "Built but not sent — dry run is on",
    accent: "border-t-ink-muted/40",
  },
  {
    key: "awaiting_user",
    title: "Your turn",
    hint: "Submit it yourself, then confirm",
    accent: "border-t-accent",
  },
  { key: "success", title: "Submitted", hint: "Delivered", accent: "border-t-good" },
  { key: "failed", title: "Failed", hint: "Needs another look", accent: "border-t-critical" },
];

export function Applications({ version }: { version: number }) {
  const { data, loading, error, refetch } = useApi(() => api.applications(), [version]);
  const settings = useApi(() => api.applySettings(), []);
  const followups = useApi(() => api.followups(), [version]);
  const [busy, setBusy] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const act = useCallback(
    async (app: Application, fn: () => Promise<unknown>) => {
      setBusy(app.id);
      setActionError(null);
      try {
        await fn();
        await refetch();
      } catch (e) {
        setActionError(e instanceof ApiError ? e.message : "Request failed");
      } finally {
        setBusy(null);
      }
    },
    [refetch],
  );

  return (
    <div className="animate-fade-up space-y-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Applications</h1>
        <p className="text-sm text-ink-muted">
          Every dispatch, including the ones that never left the machine.
        </p>
      </div>

      {settings.data && <GateBanner settings={settings.data} />}
      {actionError && (
        <Card className="flex items-start gap-2 border-critical/40 bg-critical/5 p-3 text-sm">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
          <span>{actionError}</span>
        </Card>
      )}

      <FollowUps
        items={followups.data ?? []}
        onChange={() => {
          followups.refetch();
          refetch();
        }}
      />

      {error ? (
        <Card className="p-6 text-sm">
          <span className="font-medium text-critical">Couldn't load applications.</span> {error}
        </Card>
      ) : loading && !data ? (
        <div className="grid gap-3 lg:grid-cols-4">
          {COLUMNS.map((c) => (
            <Skeleton key={c.key} className="h-48 rounded-card" />
          ))}
        </div>
      ) : !data?.length ? (
        <Card>
          <CardBody className="py-16 text-center text-sm text-ink-muted">
            Nothing dispatched yet. Approve a tailored CV, then hit Apply on the job.
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-4">
          {COLUMNS.map((col) => {
            const items = data.filter((a) => a.result === col.key);
            return (
              <section key={col.key} className="flex flex-col gap-2">
                <header className={cn("rounded-t-card border-t-2 px-1 pt-2", col.accent)}>
                  <div className="flex items-baseline justify-between">
                    <h2 className="font-display text-sm font-semibold">{col.title}</h2>
                    <span className="font-mono text-[11px] text-ink-muted">{items.length}</span>
                  </div>
                  <p className="text-[11px] leading-tight text-ink-muted">{col.hint}</p>
                </header>
                <div className="flex flex-col gap-2">
                  {items.map((app) => (
                    <ApplicationCard
                      key={app.id}
                      app={app}
                      busy={busy === app.id}
                      onConfirm={() => act(app, () => api.confirmSubmit(app.job_id))}
                      onFail={() => {
                        const reason = window.prompt("What went wrong?") ?? "";
                        if (reason.trim()) act(app, () => api.reportFailure(app.job_id, reason));
                      }}
                      onRetry={() => act(app, () => api.applyJob(app.job_id))}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function GateBanner({ settings }: { settings: ApplySettings }) {
  const sending = settings.email_enabled && !settings.email_dry_run;
  const redirected = sending && !!settings.email_test_recipient;

  return (
    <Card
      className={cn(
        "border-l-2",
        sending && !redirected ? "border-l-critical" : "border-l-good",
      )}
    >
      <CardBody className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium">
          <ShieldCheck size={15} className={sending && !redirected ? "text-critical" : "text-good"} />
          Email channel
        </span>
        {!settings.email_enabled ? (
          <span className="text-ink-muted">
            off — nothing can be sent ({settings.email_blocker || "apply.email.enabled is false"})
          </span>
        ) : settings.email_dry_run ? (
          <span className="text-ink-muted">
            dry run — messages are built and recorded, never sent
          </span>
        ) : redirected ? (
          <span className="text-ink-muted">
            live, but redirected to{" "}
            <span className="font-mono text-ink">{settings.email_test_recipient}</span> instead of
            employers
          </span>
        ) : (
          <span className="font-medium text-critical">
            live — applications really go to employers from {settings.email_from}
          </span>
        )}
        <span className="ml-auto text-xs text-ink-muted">edit config.yaml → apply.email</span>
      </CardBody>
    </Card>
  );
}

function ApplicationCard({
  app,
  busy,
  onConfirm,
  onFail,
  onRetry,
}: {
  app: Application;
  busy: boolean;
  onConfirm: () => void;
  onFail: () => void;
  onRetry: () => void;
}) {
  const email = app.meta.email;
  const handoff = app.meta.handoff;

  return (
    <Card className="p-3">
      <Link
        to={`/jobs/${encodeURIComponent(app.job_id)}/review`}
        className="block font-medium leading-tight hover:text-accent"
      >
        {app.job_title}
      </Link>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
        <span>{app.company}</span>
        {app.channel && (
          <Badge className="border-ink/10 text-ink-muted">
            {app.channel === "email" ? <Mail size={10} /> : <ExternalLink size={10} />}
            {app.channel}
          </Badge>
        )}
        <span>{relativeTime(app.submitted_at ?? app.created_at)}</span>
      </div>

      {email && (
        <p className="mt-2 rounded-md border bg-surface-2/60 px-2 py-1 text-[11px] leading-relaxed text-ink-muted">
          {email.redirected ? (
            <>
              → <span className="font-mono text-ink">{email.to}</span>{" "}
              <span className="opacity-70">(test redirect from {email.intended_to})</span>
            </>
          ) : (
            <>
              → <span className="font-mono text-ink">{email.to}</span>
            </>
          )}
          {email.attachments.length > 0 && <> · {email.attachments.join(", ")}</>}
        </p>
      )}

      {app.error_msg && (
        <p className="mt-2 rounded-md border border-critical/30 bg-critical/5 px-2 py-1 text-[11px] leading-relaxed text-critical">
          {app.error_msg}
        </p>
      )}

      {handoff && (
        <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">{handoff.note}</p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {app.result === "awaiting_user" && (
          <>
            {app.apply_target && (
              <a
                href={app.apply_target}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[12px] font-medium text-ink-muted hover:bg-surface-2 hover:text-ink"
              >
                <ExternalLink size={12} /> Open form
              </a>
            )}
            <Button size="sm" className="h-7 px-2 text-[12px]" onClick={onConfirm} disabled={busy}>
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} I sent it
            </Button>
            <Button
              size="sm"
              variant="danger"
              className="h-7 px-2 text-[12px]"
              onClick={onFail}
              disabled={busy}
            >
              <X size={12} /> Failed
            </Button>
          </>
        )}
        {(app.result === "failed" || app.result === "dry_run") && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[12px]"
            onClick={onRetry}
            disabled={busy}
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            {app.result === "dry_run" ? "Run again" : "Retry"}
          </Button>
        )}
        <a
          href={`/jobs/${encodeURIComponent(app.job_id)}/review`}
          className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] text-ink-muted hover:bg-surface-2 hover:text-ink"
        >
          <FileText size={12} /> CV
        </a>
      </div>
    </Card>
  );
}
