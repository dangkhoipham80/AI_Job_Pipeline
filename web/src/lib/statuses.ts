import type { JobStatus } from "@/types";

/**
 * What each job status means, in one place.
 *
 * The status vocabulary is the spine of the whole app — the funnel, the filter
 * dropdown, the pills in the table and the Guide page all name the same nine
 * states. Describing them in nine different components is how those wordings
 * drift apart, so every surface reads from here.
 *
 * `actor` answers the only question that matters when you are staring at a
 * board: is this waiting on me, or on the agent?
 */
export interface StatusInfo {
  /** Who moves it forward from here. */
  actor: "you" | "agent" | "done";
  /** One line: what the state means. */
  meaning: string;
  /** What happens next, phrased as the action you'd take. */
  next: string;
}

export const STATUS_INFO: Record<JobStatus, StatusInfo> = {
  DISCOVERED: {
    actor: "you",
    meaning: "A crawl found this job. Nobody has judged it yet.",
    next: "Read the title and company, then Shortlist it or Skip it.",
  },
  SHORTLISTED: {
    actor: "you",
    meaning: "You decided this one is worth a CV of its own.",
    next: "Hit Tailor CV — that's when the agent starts spending time and API budget.",
  },
  TAILORING: {
    actor: "agent",
    meaning:
      "Claude is reworking your master CV against this job description — reordering and trimming what you already have, never inventing anything.",
    next: "Wait. This takes roughly a minute, including the LaTeX build.",
  },
  REVIEW: {
    actor: "you",
    meaning: "The tailored CV is built and waiting for your eyes.",
    next: "Read the diff and the gap report, then Approve — or send an edit instruction and let it try again.",
  },
  APPROVED: {
    actor: "you",
    meaning: "You signed off on the CV. Nothing has been sent yet.",
    next: "Hit Apply. What happens then depends on the channel (see below).",
  },
  SUBMITTING: {
    actor: "agent",
    meaning: "The dispatcher is sending the application right now.",
    next: "Wait — this is the one state that touches the outside world.",
  },
  SUBMITTED: {
    actor: "done",
    meaning: "The application is out: sent by email, or you confirmed you submitted it yourself.",
    next: "Nothing. It's in their hands now.",
  },
  FAILED: {
    actor: "you",
    meaning: "Something broke — usually the mail server refusing, or a portal that changed.",
    next: "Read the error on the Applications board, fix it, and retry.",
  },
  SKIPPED: {
    actor: "done",
    meaning: "You passed on it. It stays in the database so a re-crawl won't resurface it.",
    next: "Nothing, unless you change your mind.",
  },
};

/** The happy path, in order. FAILED and SKIPPED are exits, not steps. */
export const FUNNEL_STEPS: JobStatus[] = [
  "DISCOVERED",
  "SHORTLISTED",
  "TAILORING",
  "REVIEW",
  "APPROVED",
  "SUBMITTED",
];

/** Short hover text for a status pill. */
export function statusTooltip(status: JobStatus): string {
  const info = STATUS_INFO[status];
  return `${info.meaning} → ${info.next}`;
}
