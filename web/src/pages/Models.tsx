import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Loader2, RefreshCw, Save, ShieldAlert } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Skeleton,
} from "@/components/ui";
import { providerColor } from "@/components/charts/palette";
import { cn } from "@/lib/utils";
import type { LlmSettings, LlmTask, Settings as SettingsData } from "@/types";

const TASKS: { key: LlmTask; label: string; blurb: string }[] = [
  {
    key: "tailor",
    label: "Tailor",
    blurb: "Reorders numbered CV items and writes one summary. Sends your whole Master CV.",
  },
  {
    key: "letter",
    label: "Cover letter",
    blurb: "300 words a stranger judges you on. Also sends your whole Master CV.",
  },
  {
    key: "classify",
    label: "Classify reply",
    blurb: "One employer email into one of six labels. The easy one — try a cheap model here.",
  },
];

/** "—" for a number nobody can know, never a zero standing in for one. */
function money(v: number | null): string {
  return v === null ? "—" : `$${v < 0.01 ? v.toFixed(4) : v.toFixed(2)}`;
}

/**
 * A rate, or the count it was withheld for. Below `min_sample` the API returns
 * null rather than a percentage: three calls with two failures is not "33%", it
 * is three calls, and a percentage invites a comparison the sample can't carry.
 */
function rate(v: number | null, attempts: number): string {
  return v === null ? `n=${attempts}` : `${Math.round(v * 100)}%`;
}

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`;
}

/**
 * Models (Phase 20b) — pick the backend for each call, next to what it costs.
 *
 * The two halves belong on one page on purpose. Choosing a model is a decision
 * you make *while looking at* what the last one billed and how often it cleared
 * the guardrails; splitting them would leave the choice to be made from memory.
 */
export function Models({ version }: { version: number }) {
  // `live` asks each provider for its current model list — one round-trip per
  // provider, so it is a button rather than something the page does on load.
  const [live, setLive] = useState(false);
  const stats = useApi(() => api.llmStats(live), [version, live]);
  const settings = useApi(() => api.settings(), [version]);
  const [draft, setDraft] = useState<LlmSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) setDraft(structuredClone(settings.data.llm));
  }, [settings.data]);

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      await api.saveSettings({ llm: draft } as Partial<SettingsData>);
      await Promise.all([settings.refetch(), stats.refetch()]);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, settings, stats]);

  const d = stats.data;

  // Provider for a task, resolving the "" = inherit rule the same way the
  // backend does, so the dropdown shows what will actually run.
  const providerOf = (task: LlmTask) => (draft ? draft[task] || draft.provider : "");
  const modelOf = (task: LlmTask) => {
    if (!draft) return "";
    return draft.task_models?.[task] || draft.models?.[providerOf(task)] || "";
  };

  const setProvider = (task: LlmTask, provider: string) =>
    setDraft((p) => (p ? { ...p, [task]: provider } : p));

  const setModel = (task: LlmTask, model: string) =>
    setDraft((p) => (p ? { ...p, task_models: { ...(p.task_models ?? {}), [task]: model } } : p));

  const setBudget = (provider: string, dollars: string) =>
    setDraft((p) =>
      p
        ? { ...p, budget_usd: { ...(p.budget_usd ?? {}), [provider]: Number(dollars) || 0 } }
        : p,
    );

  const byProvider = useMemo(() => {
    const out: Record<
      string,
      { model: string; input: number; output: number; available: boolean }[]
    > = {};
    for (const m of d?.catalogue ?? []) {
      (out[m.provider] ??= []).push({
        model: m.model,
        input: m.input_per_mtok,
        output: m.output_per_mtok,
        available: m.available,
      });
    }
    return out;
  }, [d]);

  const totals = useMemo(() => {
    const rows = d?.backends ?? [];
    const priced = rows.filter((r) => r.cost_usd !== null);
    return {
      spend: priced.reduce((a, r) => a + (r.cost_usd ?? 0), 0),
      anyPriced: priced.length > 0,
      calls: rows.reduce((a, r) => a + r.attempts, 0),
      unpriced: rows.reduce((a, r) => a + r.unpriced_rounds, 0),
    };
  }, [d]);

  // One measure, one axis: cost per backend. Scaled to the largest so the bars
  // encode magnitude rather than rank.
  const costRows = useMemo(() => {
    const rows = (d?.backends ?? []).filter((r) => r.cost_usd !== null && r.cost_usd > 0);
    rows.sort((a, b) => (b.cost_usd ?? 0) - (a.cost_usd ?? 0));
    return rows;
  }, [d]);
  const costMax = costRows.length ? (costRows[0].cost_usd ?? 0) : 0;

  if (stats.loading || settings.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Models</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Which model runs which call, and what each one has cost. Defaults change nothing
          until you save.
        </p>
      </div>

      {/* A stale environment variable beating .env looks exactly like a bad key,
          which is why it gets a banner rather than a line in a log. */}
      {(d?.shadowed_env?.length ?? 0) > 0 && (
        <Card className="border-amber-500/50">
          <CardBody className="flex gap-3 py-4">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-500" />
            <div className="text-sm">
              <p className="font-medium">
                {d?.shadowed_env.join(", ")} is set as an environment variable and in{" "}
                <code className="rounded bg-muted px-1">.env</code>, with different values.
              </p>
              <p className="mt-1 text-muted-foreground">
                The environment variable wins, so your <code>.env</code> edit is being ignored.
                On Windows: <code className="rounded bg-muted px-1">setx NAME ""</code>, then open
                a new terminal.
              </p>
            </div>
          </CardBody>
        </Card>
      )}

      {/* ---- KPI row. Hero numbers, no plot — a stat tile is the right form
              for a single figure, and three of them read faster than a chart. */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardBody className="py-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Recorded spend</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {totals.anyPriced ? money(totals.spend) : "—"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {totals.unpriced > 0
                ? `${totals.unpriced} round(s) had no price — estimate excludes them`
                : "across every recorded round"}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="py-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Model calls</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{totals.calls}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              rates appear from {d?.min_sample ?? 10} calls per backend
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="py-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Providers ready</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {Object.values(d?.providers ?? {}).filter(Boolean).length}
              <span className="text-base font-normal text-muted-foreground">
                /{Object.keys(d?.providers ?? {}).length}
              </span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {Object.entries(d?.providers ?? {})
                .filter(([, ok]) => !ok)
                .map(([n]) => `${n}: no key`)
                .join(", ") || "all keys present"}
            </p>
          </CardBody>
        </Card>
      </div>

      {/* ---- Budget per provider. A meter, not a chart: one value against one
              target, three times over. ---- */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Credit used and left</CardTitle>
          <Button
            variant="ghost"
            onClick={() => setLive((v) => !v)}
            title="Ask each provider which models your key can use"
          >
            <RefreshCw className={cn("h-4 w-4", stats.loading && "animate-spin")} />
            {live ? "Live models on" : "Fetch live models"}
          </Button>
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-muted-foreground">
            “Left” is your budget minus what <em>JobPilot</em> recorded spending — not a balance
            read from the vendor. Every provider’s spend endpoint needs an <em>Admin</em> key,
            which this app deliberately does not hold, so usage from anywhere else is invisible
            here.
          </p>
          {(d?.spend ?? []).map((s) => {
            const pct =
              s.budget_usd && s.budget_usd > 0
                ? Math.min(100, (s.spent_usd / s.budget_usd) * 100)
                : 0;
            return (
              <div key={s.provider} className="space-y-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2 font-medium">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: providerColor(s.provider) }}
                    />
                    {s.provider}
                    {!s.has_key && <span className="text-muted-foreground">(no key)</span>}
                    {live && (
                      <span className="text-xs font-normal text-muted-foreground">
                        {s.models.length
                          ? `${s.models.length} models offered`
                          : "model list unavailable"}
                      </span>
                    )}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    <span className="font-medium text-foreground">{money(s.spent_usd)}</span> used
                    {s.remaining_usd !== null && <> · {money(s.remaining_usd)} left</>}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <span
                      className="block h-full rounded-full"
                      style={{ width: `${pct}%`, background: providerColor(s.provider) }}
                    />
                  </span>
                  <label className="flex items-center gap-1 text-xs text-muted-foreground">
                    budget $
                    <Input
                      type="number"
                      step="1"
                      min="0"
                      className="h-7 w-20"
                      value={draft?.budget_usd?.[s.provider] ?? ""}
                      onChange={(e) => setBudget(s.provider, e.target.value)}
                    />
                  </label>
                </div>
                {s.unpriced_rounds > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {s.unpriced_rounds} round(s) ran on a model with no price on file — not
                    counted above.
                  </p>
                )}
              </div>
            );
          })}
          <p className="text-xs text-muted-foreground">
            Budgets save with the button below.
          </p>
        </CardBody>
      </Card>

      {/* ---- The picker ---- */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Which model runs which call</CardTitle>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-500">
                <Check className="h-4 w-4" /> Saved
              </span>
            )}
            <Button onClick={save} disabled={saving || !draft}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save
            </Button>
          </div>
        </CardHeader>
        <CardBody className="space-y-5">
          {saveError && <p className="text-sm text-red-600 dark:text-red-400">{saveError}</p>}

          {TASKS.map(({ key, label, blurb }) => {
            const provider = providerOf(key);
            const reachable = d?.providers?.[provider] ?? true;
            const blocker = d?.blockers?.[key];
            const warns = d?.warnings?.[key] ?? [];
            return (
              <div key={key} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: providerColor(provider) }}
                  />
                  <span className="font-medium">{label}</span>
                  {!reachable && <Badge className="border-amber-500/50 text-amber-700 dark:text-amber-500">no API key</Badge>}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{blurb}</p>

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="text-sm">
                    <span className="text-muted-foreground">Provider</span>
                    <Select
                      className="mt-1"
                      value={provider}
                      onChange={(e) => setProvider(key, e.target.value)}
                    >
                      {Object.keys(d?.providers ?? {}).map((p) => (
                        <option key={p} value={p}>
                          {p}
                          {d?.providers?.[p] ? "" : " (no key)"}
                        </option>
                      ))}
                    </Select>
                  </label>

                  <label className="text-sm">
                    <span className="text-muted-foreground">Model</span>
                    <Select
                      className="mt-1"
                      value={modelOf(key)}
                      onChange={(e) => setModel(key, e.target.value)}
                    >
                      <option value="">provider default</option>
                      {(byProvider[provider] ?? []).map((m) => (
                        <option key={m.model} value={m.model}>
                          {m.model} — ${m.input}/${m.output} per Mtok
                          {m.available ? "" : " (not offered to your key)"}
                        </option>
                      ))}
                    </Select>
                  </label>
                </div>

                {blocker && (
                  <p className="mt-2 flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-500">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    {blocker}
                  </p>
                )}
                {warns.map((w) => (
                  <p
                    key={w}
                    className="mt-2 flex items-start gap-1.5 text-sm text-red-600 dark:text-red-400"
                  >
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    {w}
                  </p>
                ))}
              </div>
            );
          })}
        </CardBody>
      </Card>

      {/* ---- Cost comparison. Horizontal bars: the labels are long model ids,
              and one measure on one axis. Every bar is directly labelled, which
              is also what discharges the light-mode contrast warning. ---- */}
      {costRows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Cost so far, by backend</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="mb-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
              {Object.keys(d?.providers ?? {}).map((p) => (
                <span key={p} className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 rounded-sm"
                    style={{ background: providerColor(p) }}
                  />
                  {p}
                </span>
              ))}
            </div>
            <ul className="space-y-2">
              {costRows.map((r) => (
                <li key={`${r.task}-${r.provider}-${r.model}`} className="flex items-center gap-3">
                  <span className="w-56 shrink-0 truncate text-sm" title={`${r.task} · ${r.model}`}>
                    <span className="text-muted-foreground">{r.task}</span> {r.model}
                  </span>
                  <span className="flex h-5 flex-1 items-center">
                    <span
                      className="h-2.5 rounded-[4px]"
                      style={{
                        width: `${Math.max(2, ((r.cost_usd ?? 0) / costMax) * 100)}%`,
                        background: providerColor(r.provider),
                      }}
                      title={`${r.provider} · ${money(r.cost_usd)}`}
                    />
                  </span>
                  <span className="w-20 shrink-0 text-right text-sm tabular-nums">
                    {money(r.cost_usd)}
                  </span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}

      {/* ---- The table view. Seven mixed measures is a table's job, and it is
              also the accessible fallback the palette check requires. ---- */}
      <Card>
        <CardHeader>
          <CardTitle>Every backend that has run</CardTitle>
        </CardHeader>
        <CardBody>
          {(d?.backends?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">
              No model calls recorded yet. Run{" "}
              <code className="rounded bg-muted px-1">jobpilot llm bench --task classify</code> or
              tailor a job.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 pr-3 font-medium">Task</th>
                    <th className="py-2 pr-3 font-medium">Model</th>
                    <th className="py-2 pr-3 text-right font-medium">Calls</th>
                    <th className="py-2 pr-3 text-right font-medium">Cost</th>
                    <th className="py-2 pr-3 text-right font-medium">1st try</th>
                    <th className="py-2 pr-3 text-right font-medium">OK</th>
                    <th className="py-2 pr-3 text-right font-medium">p50</th>
                    <th className="py-2 text-right font-medium">p95</th>
                  </tr>
                </thead>
                <tbody>
                  {d?.backends.map((r) => (
                    <tr key={`${r.task}-${r.provider}-${r.model}`} className="border-b last:border-0">
                      <td className="py-2 pr-3">{r.task}</td>
                      <td className="py-2 pr-3">
                        <span className="flex items-center gap-2">
                          <span
                            aria-hidden
                            className="h-2.5 w-2.5 shrink-0 rounded-full"
                            style={{ background: providerColor(r.provider) }}
                          />
                          <span className="truncate">{r.model}</span>
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{r.attempts}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(r.cost_usd)}</td>
                      <td
                        className={cn(
                          "py-2 pr-3 text-right tabular-nums",
                          r.first_try_rate === null && "text-muted-foreground",
                        )}
                      >
                        {rate(r.first_try_rate, r.attempts)}
                      </td>
                      <td
                        className={cn(
                          "py-2 pr-3 text-right tabular-nums",
                          r.success_rate === null && "text-muted-foreground",
                        )}
                      >
                        {rate(r.success_rate, r.attempts)}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{ms(r.p50_latency_ms)}</td>
                      <td className="py-2 text-right tabular-nums">{ms(r.p95_latency_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-muted-foreground">
                “1st try” is the share of calls the guardrails accepted without a corrective
                round — the quality number. Rates are withheld below {d?.min_sample ?? 10} calls
                and shown as a count instead. “—” under Cost means the model is not in the price
                table, which is not the same as free.
              </p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
