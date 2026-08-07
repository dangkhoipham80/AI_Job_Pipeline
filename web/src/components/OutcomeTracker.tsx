import { useCallback, useRef, useState } from "react";
import { CircleSlash, Loader2, Undo2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Application, ApplicationEvent, OutcomeType } from "@/types";

/**
 * What happened after the application went out (Phase 18).
 *
 * Lives inside the board card rather than on a page of its own: the moment you
 * know an outcome is the moment you are looking at the application, and making
 * that a navigation is how a field stops getting filled in.
 *
 * A card with no outcome shows a prompt, not an empty badge — "nothing recorded
 * yet" is a question the board is asking you, not a state of the world.
 */

const OPTIONS: { key: OutcomeType; label: string; className: string }[] = [
  { key: "replied", label: "They replied", className: "border-caution/40 text-caution" },
  { key: "interview", label: "Interview", className: "border-accent/40 text-accent" },
  { key: "offer", label: "Offer", className: "border-good/40 text-good" },
  { key: "rejected", label: "Rejected", className: "border-critical/40 text-critical" },
  { key: "withdrawn", label: "I withdrew", className: "border-ink/15 text-ink-muted" },
  { key: "ghosted", label: "Ghosted", className: "border-ink/15 text-ink-muted" },
];

const BY_KEY = Object.fromEntries(OPTIONS.map((o) => [o.key, o])) as Record<
  OutcomeType,
  (typeof OPTIONS)[number]
>;

export function OutcomeTracker({ app, onChange }: { app: Application; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // The in-flight guard has to be a ref, not the state above. Two clicks in one
  // tick both read `busy === false` — React hasn't re-rendered between them —
  // so a state check lets the second one through and writes a duplicate event.
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ApplicationEvent[] | null>(null);

  const loadEvents = useCallback(async () => {
    try {
      setEvents(await api.applicationEvents(app.id));
    } catch {
      setEvents([]);
    }
  }, [app.id]);

  const toggle = useCallback(() => {
    const next = !open;
    setOpen(next);
    setError(null);
    if (next && app.outcome_stage) void loadEvents();
  }, [open, app.outcome_stage, loadEvents]);

  const run = useCallback(
    async (fn: () => Promise<unknown>) => {
      // Harmless to the rates — they count applications, not events — but a
      // duplicate row in a history whose whole job is being readable is not.
      if (inFlight.current) return;
      inFlight.current = true;
      setBusy(true);
      setError(null);
      try {
        await fn();
        await loadEvents();
        onChange();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Request failed");
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [loadEvents, onChange],
  );

  const current = app.outcome_stage ? BY_KEY[app.outcome_stage] : null;

  return (
    <div className="mt-2 border-t border-line pt-2">
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-1.5 text-left text-[11px] text-ink-muted hover:text-ink"
      >
        {current ? (
          <>
            <Badge className={cn("py-0", current.className)}>{current.label}</Badge>
            <span className="truncate">{app.outcome_hint}</span>
          </>
        ) : (
          <span className="inline-flex items-center gap-1 underline decoration-dotted underline-offset-2">
            <CircleSlash size={11} /> No outcome recorded — what happened?
          </span>
        )}
        {busy && <Loader2 size={11} className="ml-auto animate-spin" />}
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap gap-1">
            {OPTIONS.map((o) => (
              <button
                key={o.key}
                type="button"
                disabled={busy}
                onClick={() => run(() => api.recordOutcome(app.id, { event_type: o.key }))}
                className={cn(
                  "rounded-md border px-1.5 py-0.5 text-[11px] font-medium hover:bg-surface-2 disabled:opacity-50",
                  o.className,
                )}
              >
                {o.key === app.outcome_stage ? `${o.label} again` : o.label}
              </button>
            ))}
          </div>

          {error && <p className="text-[11px] text-critical">{error}</p>}

          {/* The log, retracted rows included: a stage that rewound has to be
              explainable from the card that shows it. */}
          {events && events.length > 0 && (
            <ul className="space-y-0.5">
              {events.map((e) => (
                <li
                  key={e.id}
                  className={cn(
                    "flex items-center gap-1.5 text-[11px] text-ink-muted",
                    e.is_retracted && "line-through opacity-60",
                  )}
                >
                  <span className="font-medium text-ink">{BY_KEY[e.event_type]?.label ?? e.event_type}</span>
                  {e.label && <span className="truncate">{e.label}</span>}
                  <span>{relativeTime(e.occurred_at)}</span>
                  {!e.is_retracted && (
                    <button
                      type="button"
                      disabled={busy}
                      title="Recorded by mistake — rewind to the previous outcome"
                      onClick={() => run(() => api.retractEvent(app.id, e.id))}
                      className="ml-auto inline-flex items-center gap-0.5 hover:text-ink"
                    >
                      <Undo2 size={10} /> retract
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
