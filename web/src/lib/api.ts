import type {
  CrawlRequest,
  CrawlSetupInfo,
  Application,
  ApplySettings,
  CvCompileResult,
  CvDocument,
  CvDocumentResponse,
  CvVersion,
  CvVersionDetail,
  Job,
  JobDetail,
  JobInput,
  JobsQuery,
  ReviewData,
  RunRecord,
  Settings,
  Stats,
  Task,
} from "@/types";

const BASE = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const TOKEN = import.meta.env.VITE_API_TOKEN ?? "changeme";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: { "X-API-Token": TOKEN, "Content-Type": "application/json", ...opts.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (null as T) : ((await res.json()) as T);
}

function qs(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

const jobPath = (id: string) => `/jobs/${id.split("/").map(encodeURIComponent).join("/")}`;
// "master" or a job id — job ids contain ':' and must survive as one segment.
const cvPath = (scope: string) => `/cv/${encodeURIComponent(scope)}`;

export const api = {
  stats: () => req<Stats>("/stats"),
  jobs: (query: JobsQuery = {}) => req<Job[]>(`/jobs${qs(query as Record<string, unknown>)}`),
  job: (id: string) => req<JobDetail>(jobPath(id)),
  /* Manual entry — the way in for postings no crawler may fetch, LinkedIn above
     all (its robots.txt disallows automated access to job pages). */
  createJob: (body: JobInput) =>
    req<JobDetail>("/jobs", { method: "POST", body: JSON.stringify(body) }),
  patchJob: (id: string, patch: Partial<JobInput>) =>
    req<JobDetail>(jobPath(id), { method: "PATCH", body: JSON.stringify(patch) }),
  shortlist: (id: string) => req<JobDetail>(`${jobPath(id)}/shortlist`, { method: "POST" }),
  skip: (id: string) => req<JobDetail>(`${jobPath(id)}/skip`, { method: "POST" }),

  /* CV Studio (Phase 4.5) */
  cv: (scope: string) => req<CvDocumentResponse>(cvPath(scope)),
  saveCv: (scope: string, document: CvDocument) =>
    req<CvDocumentResponse>(cvPath(scope), { method: "PUT", body: JSON.stringify(document) }),
  compileCv: (scope: string) => req<CvCompileResult>(`${cvPath(scope)}/compile`, { method: "POST" }),
  cvVersions: (scope: string) => req<CvVersion[]>(`${cvPath(scope)}/versions`),
  cvVersion: (scope: string, version: number) =>
    req<CvVersionDetail>(`${cvPath(scope)}/versions/${version}`),
  rollbackCv: (scope: string, version: number) =>
    req<CvDocumentResponse>(`${cvPath(scope)}/rollback/${version}`, { method: "POST" }),

  /** Fetch the compiled PDF as an object URL (the <iframe> can't send the token). */
  cvPdfUrl: async (scope: string): Promise<string> => {
    const res = await fetch(`${BASE}${cvPath(scope)}/pdf`, { headers: { "X-API-Token": TOKEN } });
    if (!res.ok) throw new ApiError(res.status, "PDF not available");
    return URL.createObjectURL(await res.blob());
  },

  /* Tailor + CV Review (Phase 5). Both run on the queue: the response is a
     task, and what it produced arrives via `review()` once it finishes.
     Follow it with `useTask` — the WebSocket pushes every step. */
  tailor: (id: string) => req<Task>(`${jobPath(id)}/tailor`, { method: "POST" }),
  editCv: (id: string, instruction: string) =>
    req<Task>(`${jobPath(id)}/edit`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  review: (id: string) => req<ReviewData>(`${jobPath(id)}/review`),
  approve: (id: string) => req<JobDetail>(`${jobPath(id)}/approve`, { method: "POST" }),
  reject: (id: string) => req<JobDetail>(`${jobPath(id)}/reject`, { method: "POST" }),

  /* Apply (Phase 6). Also queued. `task.result.result` says what actually
     happened — a finished task can still mean "nothing was sent" (dry run) or
     "your turn" (portal), and neither is a success. */
  applyJob: (id: string, coverLetter?: boolean) =>
    req<Task>(`${jobPath(id)}/apply`, {
      method: "POST",
      body: JSON.stringify({ cover_letter: coverLetter ?? null }),
    }),
  confirmSubmit: (id: string) => req<JobDetail>(`${jobPath(id)}/confirm-submit`, { method: "POST" }),
  reportFailure: (id: string, reason: string) =>
    req<JobDetail>(`${jobPath(id)}/report-failure`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  applications: (result?: string) =>
    req<Application[]>(`/applications${qs({ result })}`),
  applySettings: () => req<ApplySettings>("/applications/settings"),

  /* Orchestration (Phase 8). Crawling can't answer inside a request, so it
     returns a task and progress arrives over the WebSocket. */
  startCrawl: (body: CrawlRequest = {}) =>
    req<Task>("/crawl", { method: "POST", body: JSON.stringify(body) }),
  crawlSetup: () => req<CrawlSetupInfo>("/crawl/setup"),
  tasks: (kind?: string) => req<Task[]>(`/tasks${qs({ kind })}`),
  task: (id: string) => req<Task>(`/tasks/${id}`),
  runs: (kind?: string) => req<RunRecord[]>(`/runs${qs({ kind })}`),
  settings: () => req<Settings>("/settings"),
  saveSettings: (patch: Partial<Settings>) =>
    req<Settings>("/settings", { method: "PUT", body: JSON.stringify(patch) }),

  tailoredPdfUrl: async (id: string): Promise<string> => {
    const res = await fetch(`${BASE}${jobPath(id)}/cv`, { headers: { "X-API-Token": TOKEN } });
    if (!res.ok) throw new ApiError(res.status, "PDF not available");
    return URL.createObjectURL(await res.blob());
  },
};

export function wsUrl(): string {
  return `${BASE.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(TOKEN)}`;
}
