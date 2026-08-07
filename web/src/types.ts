// Mirrors jobpilot/api/schemas.py.

export type JobStatus =
  | "DISCOVERED"
  | "SHORTLISTED"
  | "TAILORING"
  | "REVIEW"
  | "APPROVED"
  | "SUBMITTING"
  | "SUBMITTED"
  | "FAILED"
  | "SKIPPED";

/** Why a job scored what it scored, and whether the posting looks live. */
export interface JobQuality {
  /** Configured stacks this job mentions. */
  matched: string[];
  /** Configured stacks it doesn't. */
  missing: string[];
  /** Advisory only: no_jd | thin_jd | stale | undated. Never hides a job. */
  flags: string[];
}

export interface Job {
  id: string;
  source: string;
  url: string;
  title: string;
  company: string;
  location: string | null;
  salary: string | null;
  level: string | null;
  posted_at: string | null;
  status: JobStatus;
  match_score: number;
  apply_channel: string | null;
  apply_target: string | null;
  crawled_at: string | null;
  /** Which crawl discovered this job (null when added by hand). */
  run_id: number | null;
  /** Advisory: why the score, and whether the posting looks live. */
  quality: JobQuality | null;
}

export interface JobDetail extends Job {
  skills: string[];
  description_md: string;
  is_fresh: boolean;
  /** Source announced the job but couldn't carry its text (LinkedIn alerts). */
  needs_jd: boolean;
}

export interface Stats {
  total: number;
  fresh: number;
  by_status: Record<JobStatus, number>;
  by_source: Record<string, number>;
  by_level: Record<string, number>;
  by_day: Record<string, number>;
  /** What happened after the applications went out (Phase 18). */
  outcomes: OutcomeStats;
}

export interface JobsQuery {
  source?: string;
  status?: JobStatus;
  level?: string;
  q?: string;
  fresh?: boolean;
  /** Only jobs discovered by this crawl. */
  run_id?: number;
  /** ISO timestamp — only jobs crawled at or after it. */
  crawled_after?: string;
  order?: "posted" | "crawled";
  limit?: number;
  offset?: number;
}

/* CV Studio (Phase 4.5) — mirrors jobpilot/cv/schema.py -------------------- */

export interface CvTheme {
  color: string;
  section_highlight: boolean;
  font_dir: string;
}

export interface CvHeader {
  first_name: string;
  last_name: string;
  position: string;
  address: string | null;
  mobile: string | null;
  email: string | null;
  homepage: string | null;
  github: string | null;
  linkedin: string | null;
  extra_info: { label: string; url: string } | null;
  quote: string | null;
}

export interface CvBulletItem {
  label: string | null;
  text: string;
  date: string | null;
}

export interface CvEducationEntry {
  degree: string;
  institution: string;
  location: string;
  date: string;
  items: string[];
}

export interface CvEntry {
  title: string;
  date: string;
  url: string | null;
  items: string[];
  role: string | null;
  tech_stack: string[];
}

interface CvSectionBase {
  key: string;
  title: string;
  enabled: boolean;
}

export type CvSection =
  | (CvSectionBase & { type: "paragraph"; text: string; small: boolean })
  | (CvSectionBase & { type: "bullets"; items: CvBulletItem[] })
  | (CvSectionBase & { type: "education"; entries: CvEducationEntry[] })
  | (CvSectionBase & { type: "experience"; entries: CvEntry[] })
  | (CvSectionBase & { type: "projects"; entries: CvEntry[] });

export type CvSectionType = CvSection["type"];

export interface CvDocument {
  schema_version: number;
  template: string;
  theme: CvTheme;
  header: CvHeader;
  sections: CvSection[];
}

export interface CvDocumentResponse {
  scope: string;
  version: number;
  document: CvDocument;
}

export interface CvVersion {
  version: number;
  author: "user" | "agent";
  created_at: string | null;
}

export interface CvVersionDetail extends CvVersion {
  document: CvDocument;
  tex: string;
}

/**
 * GET /cv/{scope}/diff — the same structural diff the review page renders, but
 * worded for a version comparison (jobpilot/tailor/diff.py VERSION_LABELS).
 * `base`/`target` echo the server's view, so label the panel from these.
 */
export interface CvVersionDiff {
  scope: string;
  base: number;
  target: number;
  base_author: "user" | "agent";
  target_author: "user" | "agent";
  diff: CvDiff;
}

/** One thing a parser could not recover from the PDF, plus how to fix it. */
export interface AtsFinding {
  level: "error" | "warning";
  code: string;
  message: string;
  fix: string;
}

/** What an applicant tracking system gets back out of the compiled PDF. */
export interface AtsReport {
  ok: boolean;
  chars: number;
  /** Which extractor read the PDF — findings mean less from a weak one. */
  engine: string;
  findings: AtsFinding[];
  keywords_found: string[];
  keywords_missing: string[];
}

export interface CvCompileResult {
  scope: string;
  version: number;
  /** Null when the build worked but the page count couldn't be read. */
  pages: number | null;
  pdf_url: string;
  /** `null` means not checked (no PDF text extractor installed), not passed. */
  ats: AtsReport | null;
}

/* Tailor + CV Review (Phase 5) — mirrors jobpilot/tailor/{schema,diff}.py ---- */

export type RequirementKind = "must_have" | "nice_to_have" | "soft";
export type RequirementStatus = "HAVE" | "PARTIAL" | "MISSING";

export interface TailorRequirement {
  text: string;
  kind: RequirementKind;
  status: RequirementStatus;
  evidence: string;
}

export interface TailorChange {
  section: string;
  what: string;
  reason: string;
}

export interface TailorPlan {
  plan_version: number;
  match_score: number;
  requirements: TailorRequirement[];
  summary: string;
  section_order: string[];
  changes: TailorChange[];
}

export type DiffStatus = "rewritten" | "hidden" | "reordered" | "trimmed" | "unchanged";

export interface SectionDiff {
  key: string;
  title: string;
  status: DiffStatus;
  notes: string[];
  before: string | null;
  after: string | null;
}

export interface CvDiff {
  order_changed: boolean;
  order_before: string[];
  order_after: string[];
  sections: SectionDiff[];
  /** Server-computed (CvDiff.changed) — don't re-derive it here and drift. */
  changed: boolean;
}

export interface ReviewData {
  job_id: string;
  version: number;
  author: "user" | "agent" | null;
  created_at: string | null;
  match_score: number | null;
  pages: number | null;
  round: number;
  instruction: string | null;
  plan: TailorPlan | null;
  diff: CvDiff | null;
  gaps: TailorRequirement[];
}

/* Apply + Applications board (Phase 6) — mirrors jobpilot/apply/ -------------- */

export type ApplyChannel = "email" | "portal" | "external";
// A 200 from /apply does not mean anything was sent — read the result.
export type ApplyResult = "success" | "dry_run" | "awaiting_user" | "failed";

export interface EmailSummary {
  to: string;
  intended_to: string | null;
  redirected: boolean;
  subject: string;
  from: string;
  attachments: string[];
  dry_run: boolean;
  body_preview: string;
}

export interface HandoffSummary {
  url: string;
  cv_path: string | null;
  fields: Record<string, string>;
  prefilled: boolean;
  note: string;
}

/** What the cover letter step produced (jobpilot/apply/dispatcher.py). */
export interface LetterSummary {
  txt: string | null;
  pdf: string | null;
  /** Why there is no PDF. Null when the build succeeded. */
  pdf_error: string | null;
}

export interface Application {
  id: number;
  job_id: string;
  job_title: string;
  company: string;
  job_status: JobStatus;
  channel: ApplyChannel | null;
  result: ApplyResult | null;
  error_msg: string | null;
  submitted_at: string | null;
  created_at: string | null;
  cv_pdf_path: string | null;
  /** The letter as sent. */
  cover_letter_path: string | null;
  /** The letter as filed. Null with a non-null `cover_letter_path` means the
   *  LaTeX build failed — `meta.letter.pdf_error` says why. */
  cover_letter_pdf_path: string | null;
  apply_target: string | null;
  meta: { email?: EmailSummary; handoff?: HandoffSummary; letter?: LetterSummary };
  /** Where this sits in the follow-up cadence: first_nudge | second_nudge | done. */
  followup_stage: string | null;
  next_followup_at: string | null;
  followup_due: boolean;
  followup_hint: string;
  /** The latest outcome recorded (Phase 18). Null means nothing recorded yet —
   *  which is not the same as nothing having happened. */
  outcome_stage: OutcomeType | null;
  outcome_hint: string;
}

/* Outcome tracking (Phase 18) — mirrors jobpilot/apply/outcome.py ------------ */

export type OutcomeType =
  | "replied"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn"
  | "ghosted";

export interface ApplicationEvent {
  id: number;
  application_id: number;
  event_type: OutcomeType;
  /** When it happened — not when you typed it in. */
  occurred_at: string | null;
  label: string | null;
  notes: string | null;
  recorded_at: string | null;
  /** Retracted rows stay in the history, struck through, so a stage that
   *  rewound is explainable. */
  is_retracted: boolean;
}

export interface OutcomeStats {
  total_real: number;
  no_outcome: number;
  /** One bucket per application, keyed on its latest live event. */
  current: Record<OutcomeType, number>;
  /** How many applications ever touched each stage. Rates use this one. */
  reached: Record<OutcomeType, number>;
  answered: number;
  /** Null, not 0, when there is nothing to divide by. */
  reply_rate: number | null;
  interview_rate: number | null;
  offer_rate: number | null;
}

export interface ApplySettings {
  email_enabled: boolean;
  email_dry_run: boolean;
  email_test_recipient: string;
  email_from: string;
  email_blocker: string;
  portal_prefill: boolean;
}

/* Orchestration (Phase 8) — mirrors jobpilot/orchestrator.py ----------------- */

export type TaskStatus = "queued" | "running" | "done" | "failed";

export interface CrawlSiteResult {
  source: string;
  ok: boolean;
  error: string | null;
  fetched: number;
  inserted: number;
  updated: number;
  duplicates: number;
  filtered: number;
  fresh: number;
}

/**
 * What a finished task produced. Deliberately thin — `/tasks` returns fifty of
 * these at once, so the heavy artifacts stay where they already live: a tailor
 * round's plan and diff come from `GET /jobs/{id}/review`, an application's
 * email and handoff details from the Applications board.
 */
export interface TaskResult {
  /* crawl */
  sites?: CrawlSiteResult[];
  totals?: Record<string, number>;
  query?: string;
  /* tailor */
  version?: number;
  round?: number;
  attempts?: number;
  pages?: number | null;
  match_score?: number;
  gaps?: number;
  /* apply — `result` is the field that matters: a finished task can still mean
     nothing was sent (dry_run), or that it's now your turn (awaiting_user). */
  channel?: ApplyChannel;
  result?: ApplyResult;
  detail?: string;
  application_id?: number | null;
}

export interface Task {
  id: string;
  /** crawl | tailor | apply */
  kind: string;
  label: string;
  job_id: string | null;
  status: TaskStatus;
  progress: string;
  result: TaskResult;
  error: string | null;
  /** Exception class name. `GuardrailViolation` means the agent tried to claim
      something the Master CV doesn't support — louder than a build failure. */
  error_kind: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunRecord {
  id: number;
  kind: string;
  started_at: string | null;
  finished_at: string | null;
  stats: Record<string, unknown>;
  /** Jobs this crawl put in the database, counted from the jobs themselves. */
  job_count: number;
}

export interface SourceSetting {
  key: string;
  tier: number;
  enabled: boolean;
}

export interface Settings {
  app: { timezone: string; edit_max_rounds: number };
  crawl: {
    jobs_per_site: number;
    /** Listing pages walked per site to reach jobs_per_site. A ceiling. */
    max_pages: number;
    fresh_hours: number;
    match_score_min: number;
    stacks: string[];
    exclude_keywords: string[];
    rate_limit_seconds: [number, number];
  };
  sources: SourceSetting[];
  apply: {
    email: {
      enabled: boolean;
      dry_run: boolean;
      test_recipient: string;
      from_addr: string;
      from_name: string;
      method: string;
      subject_template: string;
    };
    portal_prefill: boolean;
  };
  cv: { master_dir: string; out_dir: string; docker_image: string; theme: string };
}

export interface JobInput {
  url?: string;
  title: string;
  company: string;
  location?: string | null;
  salary?: string | null;
  description_md?: string;
  skills?: string[];
  apply_channel?: string;
  apply_target?: string | null;
}

// Pipeline order for the funnel (PLAN.md §4 state machine).
export const FUNNEL_ORDER: JobStatus[] = [
  "DISCOVERED",
  "SHORTLISTED",
  "TAILORING",
  "REVIEW",
  "APPROVED",
  "SUBMITTING",
  "SUBMITTED",
];

/** One crawl's scope. All optional; omitted fields fall back to Settings. */
export interface CrawlRequest {
  query?: string;
  sources?: string[];
  limit?: number;
}

/** A source as the crawl form sees it. */
export interface CrawlSource {
  key: string;
  /** Turned on in Settings. */
  enabled: boolean;
  /** A scraper is actually registered for it — enabled but not ready would
      produce a crawl that silently does nothing. */
  ready: boolean;
}

/** Everything the crawl setup form needs, straight from the backend. */
export interface CrawlSetupInfo {
  /** Technologies from your CV, most-supported first. */
  tech: string[];
  /** Job titles from your experience, seniority stripped. */
  roles: string[];
  /** The stacks configured in Settings. */
  stacks: string[];
  /** What a crawl searches for when you type nothing. */
  default_query: string;
  jobs_per_site: number;
  sources: CrawlSource[];
}
