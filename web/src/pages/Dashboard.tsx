import { Flame, Layers, Send, Sparkles, Target } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { StatCard } from "@/components/StatCard";
import { ApproachFunnel } from "@/components/ApproachFunnel";
import { BySourceChart } from "@/components/charts/BySourceChart";
import { ByDayChart } from "@/components/charts/ByDayChart";
import { Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";

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
        <StatCard
          label="Success"
          value={successRate === null ? "—" : `${successRate}%`}
          icon={<Target size={16} />}
          note={decided === 0 ? "no results yet" : `${s.SUBMITTED}/${decided} landed`}
        />
      </div>

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
