import { useCallback, useRef, useState } from "react";
import { AlertTriangle, Check, Inbox, Loader2, Mail, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { InboxSettings, InboxSuggestion, MatchConfidence } from "@/types";

/**
 * Replies found in your mailbox, and what they look like they mean (Phase 19).
 *
 * Every row is a proposal. Nothing here has been written to an application yet
 * — the quote is shown precisely so you can disagree with the label by reading
 * one line, and the buttons are the only thing that makes any of it real.
 */

const VERDICT_LABEL: Record<string, { text: string; className: string }> = {
  replied: { text: "They replied", className: "border-caution/40 text-caution" },
  interview: { text: "Interview", className: "border-accent/40 text-accent" },
  offer: { text: "Offer", className: "border-good/40 text-good" },
  rejected: { text: "Rejected", className: "border-critical/40 text-critical" },
};

/** How much the match itself should be trusted, said plainly. */
const CONFIDENCE_NOTE: Record<MatchConfidence | "", string> = {
  thread: "certain — this answers the message we sent",
  address: "the address we applied to",
  domain: "same domain we applied to",
  company: "guessed from the sender's domain",
  "": "",
};

export function InboxReplies({
  items,
  settings,
  onChange,
}: {
  items: InboxSuggestion[];
  settings: InboxSettings | null;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const act = useCallback(
    async (id: number, what: "accept" | "dismiss") => {
      if (inFlight.current) return;
      inFlight.current = true;
      setBusy(id);
      setError(null);
      try {
        await (what === "accept" ? api.acceptSuggestion(id) : api.dismissSuggestion(id));
        onChange();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Request failed");
      } finally {
        inFlight.current = false;
        setBusy(null);
      }
    },
    [onChange],
  );

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      await api.syncInbox();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Request failed");
    } finally {
      setSyncing(false);
    }
  }, []);

  // Nothing to show and nothing to offer: don't take up room on the board.
  if (!items.length && !settings?.enabled) return null;

  return (
    <Card className={cn("p-4", items.length && "border-accent/40 bg-accent/5")}>
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <Inbox size={15} className={cn("shrink-0", items.length ? "text-accent" : "text-ink-muted")} />
        <h2 className="text-sm font-semibold">
          {items.length
            ? `${items.length} repl${items.length > 1 ? "ies" : "y"} found in your mailbox`
            : "No new replies in your mailbox"}
        </h2>
        <span className="text-xs text-ink-muted">
          nothing is recorded until you say so
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={sync}
          disabled={syncing || !settings?.enabled}
          title={settings?.blocker || `Read ${settings?.folder ?? "INBOX"} again`}
        >
          {syncing ? <Loader2 size={13} className="animate-spin" /> : <Mail size={13} />}
          Check mail
        </Button>
      </header>

      {settings?.blocker && (
        <p className="mb-2 text-xs text-ink-muted">{settings.blocker}</p>
      )}
      {error && (
        <p className="mb-2 flex items-center gap-1.5 text-xs text-critical">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      <ul className="space-y-2">
        {items.map((s) => {
          const verdict = VERDICT_LABEL[s.verdict] ?? {
            text: s.verdict,
            className: "border-ink/15 text-ink-muted",
          };
          return (
            <li key={s.id} className="rounded-lg border border-line bg-surface px-3 py-2">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <Badge className={cn("py-0", verdict.className)}>{verdict.text}</Badge>
                <span className="font-medium">{s.job_title}</span>
                <span className="text-ink-muted">· {s.company}</span>
                {s.round_label && <span className="text-xs text-ink-muted">{s.round_label}</span>}
                <span className="ml-auto text-xs text-ink-muted">
                  {relativeTime(s.mail_date)}
                </span>
              </div>

              {/* The evidence, verbatim. A label you can't check against the
                  message is a label you have to take on faith. */}
              {s.quote && (
                <blockquote className="mt-1.5 border-l-2 border-line pl-2 text-[12px] italic leading-relaxed text-ink-muted">
                  “{s.quote}”
                </blockquote>
              )}

              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-[11px] text-ink-muted">
                  {s.mail_from}
                  {s.match_confidence && ` · ${CONFIDENCE_NOTE[s.match_confidence]}`}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    size="sm"
                    className="h-7 px-2 text-[12px]"
                    disabled={busy === s.id}
                    onClick={() => act(s.id, "accept")}
                  >
                    {busy === s.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Check size={12} />
                    )}
                    Record it
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-[12px]"
                    disabled={busy === s.id}
                    onClick={() => act(s.id, "dismiss")}
                  >
                    <X size={12} /> Not this
                  </Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
