import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { TooltipBox, axisColor, gridColor } from "@/components/charts/ChartFrame";
import { categorical, sourceColor } from "@/components/charts/palette";
import { cn } from "@/lib/utils";
import type { Facet, FacetRow } from "@/types";

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "skills", label: "Skills" },
  { id: "salary", label: "Salary" },
  { id: "cities", label: "Locations" },
  { id: "levels", label: "Seniority" },
  { id: "match", label: "Match score" },
  { id: "quality", label: "Posting quality" },
  { id: "sources", label: "Sources" },
  { id: "calendar", label: "Posting calendar" },
];

/**
 * How much of the corpus a chart actually saw.
 *
 * Printed as "23 of 73 jobs", never as a bare percentage: the percentage is the
 * thing that makes a sparse facet look authoritative. LinkedIn is the largest
 * source here and carries no skills, no salary and no tags, so most facets are
 * describing a minority of the market and have to say so.
 */
function Coverage({ facet }: { facet: Facet }) {
  return (
    <span className="text-xs font-normal text-muted-foreground">
      {facet.covered} of {facet.total} jobs
    </span>
  );
}

function Note({ facet }: { facet: Facet }) {
  if (!facet.note) return null;
  return (
    <p className="mt-3 flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-500">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      {facet.note}
    </p>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-24 place-items-center text-sm text-muted-foreground">{children}</div>
  );
}

/** Horizontal bars, directly labelled — the right form when the labels are
 *  long words and the measure is a simple count. */
function FacetBars({ facet, color }: { facet: Facet; color?: (key: string) => string }) {
  const rows = facet.rows.filter((r) => r.key !== "_summary");
  if (!rows.length) return <Empty>Nothing to show yet.</Empty>;
  // One measure, one colour. Cycling the categorical palette down the rows
  // would colour by *rank*, which encodes nothing and reads as if it did — the
  // hue would change the moment a filter reorders the bars. Only a facet whose
  // rows are genuinely distinct entities (sources) passes a colour function.
  const single = categorical()[0];
  return (
    <ResponsiveContainer width="100%" height={Math.max(rows.length * 30, 90)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 44, top: 4, bottom: 4 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="key"
          width={132}
          tick={{ fontSize: 12, fill: axisColor() }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={false}
          content={({ payload }) =>
            payload?.length ? (
              <TooltipBox
                label={String(payload[0].payload.key)}
                rows={[{ key: "jobs", value: String(payload[0].payload.count) }]}
              />
            ) : null
          }
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}>
          {rows.map((r) => (
            <Cell key={r.key} fill={color ? color(r.key) : single} />
          ))}
          <LabelList
            dataKey="count"
            position="right"
            className="fill-muted-foreground"
            fontSize={12}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Vertical bars for an ordered distribution (a histogram), where the x axis
 *  carries meaning and reordering it would destroy that. */
function FacetHistogram({ facet, fill }: { facet: Facet; fill: string }) {
  const rows = facet.rows.filter((r) => r.key !== "_summary");
  if (!rows.length || rows.every((r) => !r.count)) return <Empty>Nothing to show yet.</Empty>;
  return (
    <ResponsiveContainer width="100%" height={190}>
      <BarChart data={rows} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
        <CartesianGrid vertical={false} stroke={gridColor()} strokeDasharray="0" />
        <XAxis
          dataKey="key"
          tick={{ fontSize: 11, fill: axisColor() }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 11, fill: axisColor() }}
          axisLine={false}
          tickLine={false}
          width={28}
        />
        <Tooltip
          cursor={false}
          content={({ payload, label }) =>
            payload?.length ? (
              <TooltipBox
                label={String(label)}
                rows={[{ key: "jobs", value: String(payload[0].value) }]}
              />
            ) : null
          }
        />
        <Bar dataKey="count" fill={fill} radius={[3, 3, 0, 0]} maxBarSize={44} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Section({
  id,
  title,
  facet,
  children,
}: {
  id: string;
  title: string;
  facet?: Facet;
  children: React.ReactNode;
}) {
  return (
    <Card id={id} className="scroll-mt-20">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {facet && <Coverage facet={facet} />}
      </CardHeader>
      <CardBody>
        {children}
        {facet && <Note facet={facet} />}
      </CardBody>
    </Card>
  );
}

/**
 * Market (Phase 21) — what the crawled corpus looks like.
 *
 * Every chart here is drawn from `jobs.payload`, so it describes **the ads this
 * crawler happened to collect**, not the Vietnamese job market. The coverage
 * line on each card is what keeps that distinction visible: a skills ranking
 * built from 18 of 73 jobs is a real finding about 18 jobs and a fiction about
 * the market, and only the denominator tells them apart.
 */
export function Market({ version }: { version: number }) {
  const { data, loading, error } = useApi(() => api.market(), [version]);
  const [active, setActive] = useState("overview");

  // Follow the scroll, not just the clicks. Highlighting only on click leaves
  // "Skills" lit while you are reading "Salary", which makes the nav actively
  // misleading on a page this tall — worse than having no highlight at all.
  useEffect(() => {
    if (!data) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActive(visible.target.id);
      },
      // Top third of the viewport: a section counts as "the one you're reading"
      // when its heading is near the top, not when it first peeks into view.
      { rootMargin: "-80px 0px -66% 0px" },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [data]);

  const salarySummary = useMemo(
    () => data?.salary.rows.find((r: FacetRow) => r.key === "_summary"),
    [data],
  );

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <Card>
        <CardBody className="py-6 text-sm text-red-600 dark:text-red-400">
          Couldn't load market data: {error}
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="flex gap-6">
      {/* Section nav. Deliberately inside the page rather than a second global
          sidebar — Layout already owns one, and adding another there would
          reshape every page to serve this one. */}
      <nav className="sticky top-20 hidden h-fit w-40 shrink-0 lg:block">
        <p className="px-3 pb-2 text-xs uppercase tracking-wide text-muted-foreground">Sections</p>
        <ul className="space-y-0.5">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                onClick={() => setActive(s.id)}
                className={cn(
                  "block rounded-lg px-3 py-1.5 text-sm transition-colors",
                  active === s.id
                    ? "bg-ink/10 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-ink/5 hover:text-foreground",
                )}
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 flex-1 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Market</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What the {data.total_jobs} crawled postings look like. These describe the ads
            JobPilot collected — not the market as a whole. Each card says how many jobs it saw.
          </p>
        </div>

        <div id="overview" className="grid gap-4 scroll-mt-20 sm:grid-cols-3">
          <Card>
            <CardBody className="py-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Postings</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{data.total_jobs}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                across {data.sources.rows.length} source(s)
              </p>
            </CardBody>
          </Card>
          <Card>
            <CardBody className="py-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Median pay (est.)
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {salarySummary ? `$${salarySummary.median_usd_month}` : "—"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {salarySummary
                  ? `per month, from ${data.salary.covered} job(s)`
                  : "no parsable salary yet"}
              </p>
            </CardBody>
          </Card>
          <Card>
            <CardBody className="py-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Clean ads</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {data.quality.rows.find((r) => r.key === "clean")?.count ?? 0}
                <span className="text-base font-normal text-muted-foreground">
                  /{data.total_jobs}
                </span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">no missing-JD or stale flag</p>
            </CardBody>
          </Card>
        </div>

        <Section id="skills" title="Most requested skills" facet={data.skills}>
          <FacetBars facet={data.skills} />
          <p className="mt-3 text-xs text-muted-foreground">
            Counted once per job from the canonical form, so “Spring Boot” and “Spring” are one
            thing. LinkedIn alerts carry no tags at all, which is most of what is missing here.
          </p>
        </Section>

        <Section id="salary" title="Pay distribution" facet={data.salary}>
          <FacetHistogram facet={data.salary} fill={categorical()[1]} />
          {salarySummary && (
            <p className="mt-3 text-xs text-muted-foreground">
              Range ${salarySummary.min_usd_month}–${salarySummary.max_usd_month}/month. Converted
              at {salarySummary.fx_rate?.toLocaleString()} VND/USD (checked{" "}
              {salarySummary.fx_checked_on}) — an estimate, not a quote.
            </p>
          )}
        </Section>

        <Section id="cities" title="Where the jobs are" facet={data.cities}>
          <FacetBars facet={data.cities} />
        </Section>

        <Section id="levels" title="Seniority mix" facet={data.levels}>
          <FacetBars facet={data.levels} />
          <p className="mt-3 text-xs text-muted-foreground">
            Level is inferred from the title and description, so an ad with neither is unknown
            rather than junior.
          </p>
        </Section>

        <Section id="match" title="Match against your stacks" facet={data.match_scores}>
          <FacetHistogram facet={data.match_scores} fill={categorical()[0]} />
          <p className="mt-3 text-xs text-muted-foreground">
            Scored at crawl time against <code>crawl.stacks</code>. A corpus bunched to the left
            means the search queries need work, not that the market does.
          </p>
        </Section>

        <Section id="quality" title="Posting quality" facet={data.quality}>
          <FacetBars facet={data.quality} />
        </Section>

        <Section id="sources" title="Where they came from" facet={data.sources}>
          <FacetBars facet={data.sources} color={sourceColor} />
        </Section>

        <Section id="calendar" title="Posted per day" facet={data.calendar}>
          <FacetHistogram facet={data.calendar} fill={categorical()[3]} />
          <p className="mt-3 text-xs text-muted-foreground">
            By <em>posting</em> date, not crawl date — the deck's “crawled per day” chart measures
            your habits, this measures the market's.
          </p>
        </Section>
      </div>
    </div>
  );
}
