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
