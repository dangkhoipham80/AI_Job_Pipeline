import { useState } from "react";
import { ArrowRight, Bot, GitCompare, RotateCcw, User } from "lucide-react";
import { Button, Card, CardBody, CardHeader, CardTitle, Select, Skeleton } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CvVersion } from "@/types";

/**
 * Append-only version list. Rollback re-saves an old version as the newest one,
 * so nothing is ever lost (jobpilot/cv/store.py).
 */
export function VersionHistory({
  versions,
  current,
  loading,
  busy,
  onRollback,
  onCompare,
}: {
  versions: CvVersion[] | null;
  current: number;
  loading: boolean;
  busy: boolean;
  onRollback: (version: number) => void;
  onCompare: (base: number, target: number) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>History</CardTitle>
        <span className="font-mono text-[11px] text-ink-muted">
          {versions?.length ?? 0} version{versions?.length === 1 ? "" : "s"}
        </span>
      </CardHeader>
      <CardBody className="pt-3">
        {loading && !versions ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : !versions?.length ? (
          <p className="text-sm text-ink-muted">No versions yet.</p>
        ) : (
          <ol className="flex max-h-64 flex-col gap-1 overflow-y-auto pr-1">
            {versions.map((v) => {
              const isCurrent = v.version === current;
              const Icon = v.author === "agent" ? Bot : User;
              return (
                <li
                  key={v.version}
                  className={cn(
                    "group flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm",
                    isCurrent ? "bg-accent/10" : "hover:bg-surface-2",
                  )}
                >
                  <span
                    className={cn(
                      "w-9 shrink-0 font-mono text-[11px]",
                      isCurrent ? "text-accent" : "text-ink-muted",
                    )}
                  >
                    v{v.version}
                  </span>
                  <Icon size={13} className="shrink-0 text-ink-muted" aria-label={v.author} />
                  <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
                    {v.created_at ? relativeTime(v.created_at) : "—"}
                  </span>
                  {isCurrent ? (
                    <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-accent">
                      current
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      className="h-7 shrink-0 px-2 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                      onClick={() => onRollback(v.version)}
                    >
                      <RotateCcw size={12} /> Restore
                    </Button>
                  )}
                </li>
              );
            })}
          </ol>
        )}

        {(versions?.length ?? 0) > 1 && <CompareRow versions={versions!} onCompare={onCompare} />}
      </CardBody>
    </Card>
  );
}

/**
 * Pick any two versions to compare. Versions are immutable, so a diff stays
 * correct once rendered — saving again doesn't invalidate what's on screen, it
 * only moves the defaults.
 */
function CompareRow({
  versions,
  onCompare,
}: {
  versions: CvVersion[];
  onCompare: (base: number, target: number) => void;
}) {
  // null = "follow the newest versions"; an explicit pick overrides it.
  const [base, setBase] = useState<number | null>(null);
  const [target, setTarget] = useState<number | null>(null);
  const effTarget = target ?? versions[0].version;
  const effBase = base ?? versions[1].version;

  const options = versions.map((v) => (
    <option key={v.version} value={v.version}>
      v{v.version}
      {v.author === "agent" ? " · agent" : ""}
    </option>
  ));

  return (
    <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
      <Select
        aria-label="Compare from"
        className="h-8 min-w-0 flex-1 text-xs"
        value={effBase}
        onChange={(e) => setBase(Number(e.target.value))}
      >
        {options}
      </Select>
      <ArrowRight size={13} className="shrink-0 text-ink-muted" />
      <Select
        aria-label="Compare to"
        className="h-8 min-w-0 flex-1 text-xs"
        value={effTarget}
        onChange={(e) => setTarget(Number(e.target.value))}
      >
        {options}
      </Select>
      <Button
        size="sm"
        variant="outline"
        className="h-8 shrink-0"
        onClick={() => onCompare(effBase, effTarget)}
      >
        <GitCompare size={13} /> Compare
      </Button>
    </div>
  );
}
