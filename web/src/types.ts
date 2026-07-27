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

export interface CvCompileResult {
  scope: string;
  version: number;
  pages: number;
  pdf_url: string;
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
}

export interface TailorResult {
  job_id: string;
  version: number;
  round: number;
  attempts: number;
  pages: number | null;
  match_score: number;
  plan: TailorPlan;
  diff: CvDiff;
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
