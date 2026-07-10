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
}

export interface JobDetail extends Job {
  skills: string[];
  description_md: string;
  is_fresh: boolean;
}

export interface Stats {
  total: number;
  fresh: number;
  by_status: Record<JobStatus, number>;
  by_source: Record<string, number>;
  by_level: Record<string, number>;
  by_day: Record<string, number>;
}

export interface JobsQuery {
  source?: string;
  status?: JobStatus;
  level?: string;
  q?: string;
  fresh?: boolean;
  limit?: number;
  offset?: number;
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
