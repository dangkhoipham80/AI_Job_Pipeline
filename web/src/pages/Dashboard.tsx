import { Flame, Layers, MessageSquare, Send, Sparkles, Target } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { StatCard } from "@/components/StatCard";
import { ApproachFunnel } from "@/components/ApproachFunnel";
import { BySourceChart } from "@/components/charts/BySourceChart";
import { ByDayChart } from "@/components/charts/ByDayChart";
import { Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import type { Stats } from "@/types";

export function Dashboard({ version }: { version: number }) {
  const { data: stats, loading, error } = useApi(() => api.stats(), [version]);

  if (error) return <ErrorState message={error} />;
  if (loading || !stats) return <DashboardSkeleton />;

  const s = stats.by_status;
  const decided = s.SUBMITTED + s.FAILED;
  const successRate = decided > 0 ? Math.round((s.SUBMITTED / decided) * 100) : null;

  return (
    <div className="animate-fade-up space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Control deck</h1>
        <p className="mt-0.5 text-sm text-ink-muted">Your pipeline, from discovery to runway.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Crawled" value={stats.total} icon={<Layers size={16} />} note="jobs in store" />
        <StatCard
          label="Fresh"
          value={stats.fresh}
          accent
          icon={<Flame size={16} />}
          note="posted < 48h"
        />
        <StatCard label="Shortlisted" value={s.SHORTLISTED} icon={<Sparkles size={16} />} note="picked to tailor" />
        <StatCard label="Applied" value={s.SUBMITTED} icon={<Send size={16} />} note="submitted" />
        {/* Not "success" — this only measures whether the dispatch itself went
            through. Once real outcomes sit in the row below, a tile reading
            "Success 100% · landed" above an application that was rejected is a
            straight contradiction. */}
        <StatCard
          label="Sent OK"
          value={successRate === null ? "—" : `${successRate}%`}
          icon={<Target size={16} />}
          note={decided === 0 ? "nothing dispatched yet" : `${s.SUBMITTED}/${decided} left the machine`}
        />
      </div>

      <OutcomeRow outcomes={stats.outcomes} />

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Approach funnel</CardTitle>
          </CardHeader>
          <CardBody>
            <ApproachFunnel stats={stats} />
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>By source</CardTitle>
          </CardHeader>
          <CardBody>
            <BySourceChart data={stats.by_source} />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Crawled per day</CardTitle>
          <span className="text-xs text-ink-muted">last 14 days</span>
        </CardHeader>
        <CardBody>
          <ByDayChart data={stats.by_day} />
        </CardBody>
      </Card>
    </div>
  );
}

/**
 * What happened after the applications went out (Phase 18).
 *
 * Rates come from `reached`, not from the board's current column: an
 * application that interviewed and was then rejected shows as "rejected"
 * today, and counting interviews that way would report the ones *stuck* in
 * interviews instead of the ones that got one.
 *
 * A rate over a handful of applications is noise wearing a percent sign, so
 * under ten the tile shows the count and says so instead.
 */
function OutcomeRow({ outcomes }: { outcomes: Stats["outcomes"] }) {
  const { total_real, answered, reached } = outcomes;
  const enough = total_real >= 10;
  const pct = (v: number | null) => (v === null || !enough ? "—" : `${Math.round(v * 100)}%`);

  const note = (n: number, of: number, what: string) =>
    total_real === 0
      ? "nothing sent yet"
      : enough
        ? `${n}/${of} ${what}`
        : `${n} of ${of} — too few to rate`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>After you apply</CardTitle>
        <span className="text-xs text-ink-muted">
          {total_real} real application{total_real === 1 ? "" : "s"} · dry runs excluded
        </span>
      </CardHeader>
      <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label="Answered"
          value={pct(outcomes.reply_rate)}
          icon={<MessageSquare size={16} />}
          note={note(answered, total_real, "got a human reply")}
        />
        <StatCard
          label="Interviews"
          value={pct(outcomes.interview_rate)}
          icon={<Sparkles size={16} />}
          note={note(reached.interview, total_real, "reached an interview")}
        />
        <StatCard
          label="Offers"
          value={reached.offer}
          accent={reached.offer > 0}
          icon={<Target size={16} />}
          note={
            reached.interview === 0
              ? "no interviews yet"
              : `from ${reached.interview} interview${reached.interview === 1 ? "" : "s"}`
          }
        />
      </CardBody>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-9 w-52" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-card" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-5">
        <Skeleton className="h-64 rounded-card lg:col-span-3" />
        <Skeleton className="h-64 rounded-card lg:col-span-2" />
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <Card>
      <CardBody className="space-y-1">
        <p className="font-medium text-critical">Couldn't reach the backend.</p>
        <p className="text-sm text-ink-muted">{message}</p>
        <p className="text-sm text-ink-muted">
          Start it with <code className="font-mono text-ink">python -m jobpilot.cli serve</code>.
        </p>
      </CardBody>
    </Card>
  );
}
