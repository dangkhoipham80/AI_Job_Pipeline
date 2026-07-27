import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Loader2, Play, Sparkles, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Button, Card, CardBody, CardHeader, CardTitle, Input, Select } from "@/components/ui";
import { sourceColor } from "@/components/charts/palette";
import { titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Crawl setup — decide the scope, then run it.
 *
 * A crawl takes minutes and is rate-limited per site, so "Crawl now" with no
 * say in what it does is an expensive way to find out you searched for the
 * wrong thing. Everything chosen here scopes one run: the sources you may crawl
 * at all still live in Settings, and nothing here is written back.
 *
 * The keyword suggestions come from your Master CV rather than a canned list,
 * so a suggested search is one you can actually back up.
 */
export function CrawlSetup({
  version,
  busy,
  blocked,
  onCrawl,
}: {
  version: number;
  busy: boolean;
  /** A crawl is already running — one at a time, or they race the same sites. */
  blocked: boolean;
  onCrawl: (body: { query?: string; sources?: string[]; limit?: number }) => Promise<void>;
}) {
  const { data: setup } = useApi(() => api.crawlSetup(), [version]);

  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState<number | "">("");
  const [picked, setPicked] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Only sources that are both switched on *and* actually implemented can be
  // picked. Offering the rest would produce a crawl that does nothing.
  const runnable = useMemo(
    () => (setup?.sources ?? []).filter((s) => s.enabled && s.ready).map((s) => s.key),
    [setup],
  );
  const off = (setup?.sources ?? []).filter((s) => !s.enabled);
  const notReady = (setup?.sources ?? []).filter((s) => s.enabled && !s.ready);

  // Default to everything enabled, but only once settings have arrived —
  // otherwise the first render would "select" an empty set.
  useEffect(() => {
    if (picked === null && runnable.length) setPicked(runnable);
  }, [runnable, picked]);

  const selected = picked ?? [];
  const suggestions = [...(setup?.roles ?? []), ...(setup?.tech ?? [])];
  const words = query.trim().split(/\s+/).filter(Boolean);

  function toggleSource(key: string) {
    setPicked((prev) => {
      const cur = prev ?? runnable;
      return cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
    });
  }

  function toggleWord(term: string) {
    const has = query.toLowerCase().includes(term.toLowerCase());
    setQuery((q) =>
      has
        ? q.replace(new RegExp(`\\s*${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "i"), "").trim()
        : `${q} ${term}`.trim(),
    );
  }

  async function start() {
    setError(null);
    try {
      await onCrawl({
        query: query.trim() || undefined,
        // Sending every source is the same as sending none, and an empty body
        // reads better in the run label ("all sources").
        sources: selected.length && selected.length < runnable.length ? selected : undefined,
        limit: typeof limit === "number" ? limit : undefined,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the crawl");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Crawl setup</CardTitle>
        <span className="text-[11px] text-ink-muted">applies to this run only</span>
      </CardHeader>
      <CardBody className="space-y-4 pt-4">
        {/* Sources */}
        <div>
          <Label>Sources</Label>
          <div className="flex flex-wrap gap-2">
            {runnable.map((key) => (
              <button
                key={key}
                onClick={() => toggleSource(key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors",
                  selected.includes(key)
                    ? "border-accent bg-accent/10 text-ink"
                    : "text-ink-muted hover:bg-surface-2",
                )}
              >
                <span
                  className="h-2 w-2 rounded-sm"
                  style={{
                    background: selected.includes(key) ? sourceColor(key) : "currentColor",
                    opacity: selected.includes(key) ? 1 : 0.4,
                  }}
                />
                {titleCase(key)}
              </button>
            ))}
            {!runnable.length && (
              <p className="text-sm text-ink-muted">
                No source is ready to crawl. Turn one on in{" "}
                <Link to="/settings" className="text-accent hover:underline">
                  Settings
                </Link>
                .
              </p>
            )}
          </div>
          {notReady.length > 0 && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-muted">
              <AlertTriangle size={11} className="text-accent" />
              On in Settings but not implemented yet:{" "}
              {notReady.map((s) => s.key).join(", ")} — they'd crawl nothing.
            </p>
          )}
          {off.length > 0 && (
            <p className="mt-1 text-[11px] text-ink-muted">
              Off in Settings: {off.map((s) => s.key).join(", ")}
            </p>
          )}
        </div>

        {/* Query + CV-derived suggestions */}
        <div>
          <Label>Search for</Label>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={setup?.default_query ? `${setup.default_query} (from Settings)` : "keywords"}
          />
          {suggestions.length > 0 && (
            <>
              <p className="mb-1.5 mt-2.5 flex items-center gap-1.5 text-[11px] text-ink-muted">
                <Sparkles size={12} className="text-accent" />
                From your CV — click to add
              </p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((term) => {
                  const on = words.some((w) => term.toLowerCase().includes(w.toLowerCase()))
                    ? query.toLowerCase().includes(term.toLowerCase())
                    : false;
                  return (
                    <button
                      key={term}
                      onClick={() => toggleWord(term)}
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-xs transition-colors",
                        on
                          ? "border-accent bg-accent/10 text-accent"
                          : "text-ink-muted hover:bg-surface-2 hover:text-ink",
                      )}
                    >
                      {on ? <X size={10} className="mr-0.5 inline" /> : null}
                      {term}
                    </button>
                  );
                })}
              </div>
            </>
          )}
          {setup && suggestions.length === 0 && (
            <p className="mt-2 text-[11px] text-ink-muted">
              No suggestions yet — fill in your skills and tech stack in{" "}
              <Link to="/cv" className="text-accent hover:underline">
                CV Studio
              </Link>{" "}
              and they'll show up here.
            </p>
          )}
        </div>

        {/* Depth + go */}
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <Label>Jobs per site</Label>
            <Select
              value={String(limit)}
              onChange={(e) => setLimit(e.target.value ? Number(e.target.value) : "")}
              className="w-44"
            >
              <option value="">Default ({setup?.jobs_per_site ?? "—"})</option>
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n} {n >= 50 ? "(slow)" : ""}
                </option>
              ))}
            </Select>
          </div>

          <Button
            onClick={start}
            disabled={busy || blocked || !selected.length}
            className="ml-auto"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            Crawl now
          </Button>
        </div>

        {blocked && (
          <p className="text-xs text-ink-muted">
            A crawl is already running. One at a time — a second would race the same sites and
            trip their rate limits.
          </p>
        )}
        {error && (
          <p className="flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/5 px-3 py-2 text-sm">
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
            {error}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-muted">{children}</p>
  );
}
