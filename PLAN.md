# 🤖 JobPilot — CV Autopilot Agent

> Agent tự động **crawl job lập trình** (ITviec, TopCV, VietnamWorks) → quản lý qua **Web Dashboard local** (control plane chính: dashboard, filter, funnel, duyệt/sửa CV) với **Slack** làm kênh thông báo + thao tác nhanh → **tự tailor CV (LaTeX)** cho job đã chọn → bạn duyệt/sửa → **nộp đơn theo kênh (hybrid)** → báo kết quả/lỗi.

Dự án này mở rộng CV Template LaTeX hiện có (`cv.tex` + `resume/*.tex`, build bằng Docker) thành một pipeline agentic hoàn chỉnh.

---

## 1. Quyết định thiết kế (đã chốt với user)

| Chủ đề | Lựa chọn | Hệ quả kiến trúc |
|---|---|---|
| **Cơ chế nộp đơn** | **Hybrid theo kênh** | Job qua **email** → agent tự gửi CV+cover letter (full-auto, an toàn). Job qua **portal/LinkedIn** → agent soạn sẵn + mở trang pre-fill, **user bấm Submit cuối** (human-in-the-loop). Fail → báo Slack. |
| **Nguồn crawl** | **ITviec + TopCV + VietnamWorks** (lõi MVP; +TopDev & mở rộng theo tier — xem §5.1.1) | Không scrape LinkedIn/Facebook (login-wall + ToS). Kiến trúc pluggable: thêm nguồn = thêm 1 scraper + 1 dòng config. |
| **Nơi chạy** | **Local, chạy tay/lịch** | Dùng IP/session thật của user → ít bị anti-bot. Không cần proxy residential. Cron nhẹ (tùy chọn). |
| **Giao diện quản lý** | **Web Dashboard local** là chính; **Slack** phụ (thông báo + thao tác nhanh) | Web: dashboard/funnel/filter/lịch sử/duyệt-sửa CV. Slack chỉ để tiện theo dõi + bấm nhanh khi rời máy. |
| **Database** | **PostgreSQL** (JSONB) | Entity quan hệ (jobs/applications/edits/status) + JD bán cấu trúc trong JSONB; mạnh cho query/aggregate dashboard. Thay cho SQLite ở bản đầu. |

**Nguyên tắc bất di bất dịch:**
1. **Không bịa** (truthfulness): agent chỉ được *nhấn mạnh/diễn đạt lại* kinh nghiệm có thật trong Master CV; **tuyệt đối không thêm** kỹ năng/kinh nghiệm không có. Xem `SKILL.md`.
2. **Human-in-the-loop cho mọi hành động gửi ra ngoài** trừ kênh email đã được user bật rõ ràng.
3. **Tôn trọng ToS + robots.txt + rate-limit**. Không auto-apply LinkedIn.

---

## 2. Kiến trúc tổng thể

```
   ┌────────────────────────────┐            ┌────────────────────────────┐
   │   WEB DASHBOARD (React)     │            │      SLACK (Bolt) — phụ     │
   │  control plane chính:       │◀──WS/REST─▶│  thông báo + nút nhanh:     │
   │  dashboard·funnel·filter·   │            │  [Chọn][Approve][Sửa][Nộp]  │
   │  review CV·settings·logs    │            └─────────────┬──────────────┘
   └──────────────┬─────────────┘                          │  (2 kênh cùng
                  │  REST + WebSocket                       │   điều khiển 1 state)
                  ▼                                         ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                     API BACKEND (FastAPI)                              │
   │        orchestrator · state machine per job · job queue               │
   └───┬──────────────┬───────────────────┬───────────────────┬────────────┘
       │ crawl        │ tailor            │ apply             │ read/write
       ▼              ▼                   ▼                   ▼
 ┌───────────┐  ┌───────────┐      ┌───────────────┐   ┌────────────────────┐
 │ CRAWLERS  │  │ TAILOR    │      │ APPLY DISPATCH│   │  PostgreSQL (JSONB) │
 │ itviec/   │  │ Claude→   │      │ email:auto    │   │  jobs·applications· │
 │ topcv/    │  │ resume/tex│      │ portal:prefill│   │  edits·status·runs  │
 │ vnworks   │  │ →Docker CV│      │ →success/fail │   └────────────────────┘
 └─────┬─────┘  └───────────┘      └───────────────┘
       │ Playwright+stealth → Job Normalizer (schema chung) → Postgres
       ▼
   (10 job/site → dashboard + Slack)
```

---

## 3. Data model

### 3.1 `Job` schema (chuẩn hoá chung cho 3 site)

```jsonc
{
  "id": "itviec:2156537",            // <source>:<native_id>, dùng để dedup
  "source": "itviec",                // itviec | topcv | vietnamworks
  "url": "https://itviec.com/...",
  "title": "Backend Engineer (Java, Spring Boot)",
  "company": "ACME Corp",
  "location": "Ho Chi Minh City",
  "salary": "1000-2000 USD",         // hoặc null / "Thương lượng"
  "posted_at": "2026-07-08",
  "level": "fresher|junior|middle|...",
  "skills": ["Java", "Spring Boot", "PostgreSQL"],   // trích từ JD
  "description_md": "…",             // full JD dạng markdown
  "apply_channel": "email|portal|external",
  "apply_target": "hr@acme.com | https://apply-url",
  "raw_html_ref": "store/raw/itviec-2156537.html",   // lưu để audit
  "crawled_at": "2026-07-09T08:00:00+07:00",
  "match_score": 0.0                 // điền ở bước tailor
}
```

### 3.2 PostgreSQL (schema `jobpilot`)

Postgres + JSONB (payload JD linh hoạt) + cột quan hệ để filter/aggregate cho dashboard. Migrations bằng Alembic.

- `jobs(id PK, source, payload JSONB, title, company, level, posted_at, status, match_score, crawled_at)` — cột rút ra từ payload để index/filter nhanh.
- `job_status` (enum): `DISCOVERED → SHORTLISTED → TAILORING → REVIEW → APPROVED → SUBMITTING → SUBMITTED | FAILED | SKIPPED`
- `applications(id PK, job_id FK, cv_pdf_path, cover_letter_path, channel, submitted_at, result, error_msg)`
- `edits(id PK, job_id FK, round, instruction, created_at)` — log vòng sửa CV.
- `runs(id PK, kind, started_at, finished_at, stats JSONB, log_ref)` — mỗi lần crawl/tailor/apply để hiện lên dashboard (số job, lỗi per-site…).
- `cv_versions(id PK, scope, job_id FK nullable, version, content JSONB, tex_snapshot, theme JSONB, author, created_at)` — version history cho CV Studio. `scope = 'master' | 'tailored'`; `content` = JSON structured của editor; `tex_snapshot` = .tex đã serialize (audit/rollback); `author = 'user' | 'agent'` (phân biệt sửa tay vs agent tailor).
- **Dedup**: `id = <source>:<native_id>` unique; thêm dedup xuyên nguồn theo `(company, normalized_title)`; không post lại job đã thấy trong N ngày.
- **Index**: `status`, `source`, `posted_at`, `match_score`, GIN trên `payload` (search JD).

---

## 4. Pipeline & State machine (per job)

```
DISCOVERED ──post Slack──▶ (user chọn) ──▶ SHORTLISTED
   │ (không chọn)                                │
   └──────────────────────────▶ SKIPPED         ▼
                                            TAILORING ──build fail──▶ FAILED
                                                 │ ok
                                                 ▼
                                     REVIEW ◀──────────┐
                                       │  user "Sửa"   │ re-tailor
                                       ├───────────────┘ (edit loop, max K vòng)
                                       │ user "Approve"
                                       ▼
                                   APPROVED ──▶ SUBMITTING
                                                    │
                              ┌── email: auto-send ─┤
                              │                     ├── portal: pre-fill + chờ user bấm
                              ▼                     ▼
                          SUBMITTED             (user confirm) ──▶ SUBMITTED
                              │                     │ fail
                              └── fail ──────────────┴──────────▶ FAILED (báo lỗi Slack)
```

---

## 5. Chi tiết module

### 5.1 `crawler/` — thu thập job
- **Công nghệ**: Playwright (Python) + stealth (playwright-stealth / patchright), 1 scraper/site kế thừa `BaseScraper`.
- **Chiến lược per-site** (dựa trên nghiên cứu 2026):
  - **ITviec** (~70% success): search rộng `"java spring boot"` → parse link từ attribute `data-search--job-selection-job-url` → fetch trang chi tiết. Bị **Cloudflare** → cần stealth + retry, session sống lâu.
  - **TopCV** (~50%): Vue.js SPA, dùng URL search trực tiếp, chờ hydration.
  - **VietnamWorks** (~60%): React/Next.js SPA. `search` API trả JD tóm tắt; full JD nằm trong `<script id="__NEXT_DATA__">` (de-hydration) → parse JSON đó.
- **Chống anti-bot & lịch sự**: đọc `robots.txt`; rate-limit (2–5s/req, jitter); user-agent thật; giới hạn N job/site/lần; cache HTML thô để tránh fetch lại; graceful fail (site nào lỗi vẫn chạy tiếp site khác).
- **Filter**: chỉ giữ job lập trình đúng level (fresher/junior backend Java/Spring, tuỳ config), lọc keyword loại trừ.
- **Output**: list `Job` đã normalize → `STORE`.
- **Tham chiếu**: [ariushieu/job-hunter](https://github.com/ariushieu/job-hunter), [tcd93/python-web-scraping](https://github.com/tcd93/python-web-scraping).

#### 5.1.1 Catalog nguồn — phân tầng theo độ crawl được & ưu tiên

Crawler thiết kế pluggable nên **thêm nguồn = thêm 1 scraper + 1 dòng config**, không đổi kiến trúc. MVP giữ Tier 1; các tier sau là roadmap.

| Tier | Nguồn | Crawl được? | Ưu tiên | Ghi chú |
|---|---|---|---|---|
| **1 — MVP (job board IT, có cấu trúc)** | **ITviec, TopDev, TopCV, VietnamWorks** | ✅ Playwright+stealth | Cao nhất | TopDev tập trung IT (rất hợp dev), TopCV volume lớn hợp fresher. Đúng đối tượng Java backend. |
| **2 — Job board mở rộng (VN + remote)** | ✅ **WeWorkRemotely** (RSS), ✅ **Arbeitnow** (JSON, có `?page=`) — đã làm ở Phase 11. Còn lại: CareerViet, Glints, Vieclam24h, JobHopin, Wellfound | ✅ feed chính thức → không cần browser, không anti-bot, JD đầy đủ trong 1 request | Trung | Glints hợp startup junior–mid. Wellfound có trang Vietnam/HCMC. **Đã kiểm tra và LOẠI**: Remotive + Jobicy (`robots.txt` cấm `/api/`), RemoteOK (`ClaudeBot: Disallow` + `Content-Signal: ai-train=no` — giống TopDev), Himalayas (API bỏ qua mọi filter + cắt `limit` xuống 20 → trả job ngoài ngành). Chi tiết ở CLAUDE.md "Nguồn tier-2 đã loại". |
| **3 — Career page công ty (qua ATS adapter)** | FPT Software, NashTech, KMS, TMA, VNG/Zalo, MoMo, Shopee, Grab, Tiki, Techcombank, VPBank, One Mount, Cốc Cốc, EPAM, Endava, Bosch, Renesas… | ✅ **nếu chạy ATS chuẩn** (Greenhouse/Lever/Ashby/Workable/Workday có JSON endpoint đoán được); ⚠️ nếu custom | Trung–cao | **Một `ATSAdapter` phủ nhiều công ty**: detect nền tảng → gọi API board tương ứng. "Job ngon thường lên career page trước / chỉ referral" → nguồn chất lượng cao. |
| **4 — Freelance/contract** | Upwork, Toptal, Arc.dev, Turing | ⚠️ mô hình khác (contract, cần profile mạnh) | Thấp | Ngoài scope tailor-CV-nộp-đơn hiện tại; để sau nếu cần. |
| **5 — Không crawl (manual/referral)** | **Facebook groups**, headhunter (Navigos, Adecco, Manpower, JAC, Robert Walters, HR2B…), Discord/Telegram/Zalo dev, alumni/meetup, **LinkedIn** | ❌ | — | FB groups & LinkedIn: login-wall + vi phạm ToS → **không auto-crawl**. Đây là kênh quan hệ/referral, JobPilot chỉ hỗ trợ gián tiếp (nhắc user, lưu CV tailored để gửi tay). |

**Insight áp dụng vào hệ thống** (từ thực tế tuyển dev VN):
- **Alert theo stack**: `config.yaml` khai báo `stacks: ["Java Spring Boot", "Backend", ...]` → crawler filter theo đó (mở rộng được: ReactJS, NodeJS, Golang, DevOps, Data Engineer, BrSE…).
- **Ưu tiên job mới (freshness)**: job dev VN tuyển nhanh → sort theo `posted_at` giảm dần, **gắn cờ 🔥 job < 48h** khi post lên Slack để user apply sớm.
- **Dedup xuyên nguồn**: cùng 1 job đăng nhiều site → dedup theo `(company, title normalized)` bên cạnh `id`, tránh spam Slack.

### 5.2 `slack/` — kênh phụ: thông báo + thao tác nhanh (Bolt Python, Socket Mode)
> Slack **không** phải nơi quản lý chính (đó là Web Dashboard §5.6). Slack để **tiện theo dõi khi rời máy** và bấm nhanh các quyết định quan trọng. Cả Slack và Web cùng điều khiển **một** state trong Postgres (thao tác ở đâu cũng đồng bộ; dashboard cập nhật realtime qua WebSocket).
- **Thông báo**: crawl xong ("🔥 12 job mới, 3 job <48h"), CV tailor xong chờ duyệt, đã nộp / lỗi nộp.
- **Post batch**: mỗi job = 1 Block Kit **Card** (title, company, salary, top skills, match hint, link) + nút **`Chọn`** (checkbox/button). 1 message tổng có nút **`Tailor các job đã chọn`** + link "Mở Dashboard".
- **Review CV**: sau khi tailor, post preview (ảnh PDF page 1 + diff tóm tắt các thay đổi so với Master CV) + 3 nút: **`✅ Approve`**, **`✏️ Sửa`**, **`🗑️ Bỏ`**.
- **Sửa**: mở **Modal** nhập yêu cầu (vd "thêm nhấn Kafka", "rút gọn summary") → re-tailor → post lại preview. Loop tối đa K vòng.
- **Nộp**: khi Approve → dispatcher chạy; báo lại **`✅ Đã nộp`** / **`⚠️ Lỗi: <chi tiết> — link nộp tay`**.
- **Kỹ thuật**: `@app.action("select_job_*")`, `@app.action("approve_*")`, `@app.action("edit_*")`, `@app.view("edit_modal")`. Mỗi nút mang `value = job_id`. `ack()` trước, update message sau.

### 5.3 `tailor/` — bộ não tailor CV (xem `SKILL.md`)
- **Input**: `Job.description_md` + **Master CV** (`resume/*.tex` hiện tại là nguồn sự thật).
- **Bước**: (1) trích requirement từ JD → (2) gap analysis vs Master CV → (3) rewrite có kiểm soát các section (`summary`, `skill`, thứ tự/nhấn mạnh `experience`/`project`) → (4) sinh **cover letter** → (5) build PDF.
- **Guardrail**: không bịa; mọi thay đổi phải map về dữ kiện có thật. Output kèm **diff giải thích** để user duyệt.
- **Build**: tạo bản sao `resume/` theo job (thư mục `out/<job_id>/`), render biến, gọi Docker LaTeX (tái dùng lệnh trong `README.md`), lấy `cv.pdf`.
- **ATS**: chèn keyword từ JD một cách tự nhiên vào phần có thật; giữ format sạch để ATS đọc được.

### 5.4 `apply/` — dispatcher nộp đơn (hybrid)
- **`email`**: build email (subject/body chuẩn hoá theo template + cover letter) đính kèm `cv.pdf` → gửi qua **Gmail API / SMTP** (dùng email user đã cấu hình). Full-auto sau khi Approve.
- **`portal`**: mở Playwright (non-headless), điều hướng tới `apply_target`, pre-fill field có thể (tên, email, upload CV) → **dừng lại**, ping Slack "đã pre-fill, bạn kiểm tra & bấm Submit". Không tự submit.
- **`external/LinkedIn`**: chỉ gom link + CV đã tailor về Slack, user tự nộp.
- **Error handling**: mọi exception → `FAILED` + message Slack có nguyên nhân + fallback link nộp tay + đường dẫn file CV.

### 5.5 `orchestrator/` — điều phối (chạy trong API backend)
- State machine per job (bảng ở §4). Là service bên trong **API Backend (FastAPI)**; kích hoạt qua REST (từ Web/Slack) hoặc CLI/cron.
- Tác vụ dài (crawl, tailor, build PDF, apply) chạy nền qua **job queue** (asyncio task / RQ / APScheduler), phát tiến độ realtime qua **WebSocket** cho dashboard và message cho Slack.
- Idempotent: đọc/ghi trạng thái từ **Postgres**; chạy lại không hỏng.

### 5.6 `web/` — Web Dashboard (control plane chính)
Backend **FastAPI** (REST + WebSocket) + Frontend **React (Vite + TypeScript) + TailwindCSS + shadcn/ui** (UI/UX gọn, hiện đại). Chạy local (`localhost`).

**Các trang:**
- **📊 Dashboard**: KPI cards (crawled / shortlisted / tailored / applied / success / fail), **funnel** theo status, biểu đồ job theo nguồn & theo ngày, tỉ lệ nộp thành công, cờ 🔥 job <48h. (Theo chuẩn dataviz: palette nhất quán light/dark.)
- **🔎 Jobs**: bảng job + **filter** (source, stack, level, salary, location, freshness) + full-text search JD + sort. Chọn nhiều job → **Shortlist / Tailor**.
- **📄 Job detail**: JD đầy đủ, skills, `match_score`, **gap report** (skill thiếu), link gốc, lịch sử.
- **🎨 CV Studio** *(trung tâm — xem §5.6.1)*: **edit CV trực tiếp** (form structured + raw LaTeX) với **live preview**, template/theme gallery, version history, diff. Dùng cho cả **Master CV** lẫn **bản tailored per-job**.
- **✍️ CV Review** (per-job): preview PDF bản tailored cạnh **diff** so với Master, nút **Approve / Sửa / Bỏ**. Nút "Sửa" có 2 đường: *nhập instruction cho agent* (re-tailor) **hoặc** *"Mở trong CV Studio"* (tự sửa tay ngay, không cần vòng agent).
- **📮 Applications (Kanban)**: cột theo status (`SHORTLISTED → … → SUBMITTED/FAILED`), kéo-thả hoặc bấm hành động; xem lỗi nộp + link nộp tay + file CV.
- **⚙️ Settings**: `stacks` alert, bật/tắt nguồn theo tier, ngưỡng `match_score`, cấu hình email apply, số vòng edit tối đa `K`, lịch cron.
- **🕹️ Runs/Logs**: lịch sử lần crawl/tailor/apply, thống kê per-site (success rate), log lỗi.

#### 5.6.1 🎨 CV Studio — editor + live preview + templates

Layout 2 cột: **trái = editor**, **phải = preview** (như Overleaf nhưng thân thiện hơn).

**Editor — dual mode:**
- **Structured mode (mặc định)**: form theo section (Summary textarea, Skills tag-input kéo-thả thứ tự, Experience/Project card có bullet list thêm/xoá/kéo, Education, Honors). Bật/tắt section, kéo đổi thứ tự section. Dữ liệu là **JSON structured** (nguồn sự thật của editor) → serialize ra `resume/*.tex` qua template engine (Jinja2), giữ đúng macro Awesome-CV (`\tech{}`, `\cvsimpleentry`…). User không cần biết LaTeX.
- **Raw LaTeX mode (nâng cao)**: Monaco editor sửa thẳng `.tex` (syntax highlight). Chuyển structured→raw một chiều có cảnh báo (raw edit thì mất khả năng round-trip về form).

**Preview — dual mode (giải quyết độ trễ compile LaTeX):**
- **⚡ HTML preview (tức thì)**: render CV từ JSON structured bằng React component mô phỏng layout Awesome-CV (font, màu theme, cấu trúc cột). <100ms, cập nhật theo từng phím gõ. Ghi rõ nhãn *"xấp xỉ"*.
- **📄 PDF thật (chính xác)**: nút "Compile" (hoặc auto debounce ~3s sau khi ngừng gõ) → API gọi Docker LaTeX build → render bằng **PDF.js** ngay trong trang, báo lỗi compile inline. Đây là bản dùng để Approve/nộp.

**Template & theme gallery:**
- Gallery thumbnail các biến thể: **theme màu Awesome-CV** (`awesome-red` hiện tại, `skyblue`, `emerald`, `orange`, `nephritis`, `darknight`, custom HEX), photo on/off, header align (C/L/R), thứ tự section. Click → apply → preview ngay.
- Kiến trúc mở để sau này thêm template class khác ngoài Awesome-CV (mỗi template = 1 bộ Jinja2 + 1 HTML-preview component).

**Version history:**
- Mỗi lần Save = 1 version (bảng `cv_versions` §3.2). Xem lại, **diff giữa 2 version bất kỳ**, rollback. Master CV và mỗi bản tailored có chuỗi version riêng (tailored fork từ Master).
- Sửa Master trong Studio **không** tự ảnh hưởng bản tailored đã tạo (tránh đổi CV đã nộp); có nút "re-base tailored từ Master mới" khi cần.

**UI/UX hiện đại:** dark/light mode, autosave + `Ctrl+S`, undo/redo, drag-and-drop, skeleton loading, toast, responsive; theo skill `frontend-design` — có cá tính riêng, không phải admin template mặc định.

**API (phác thảo):** `GET /jobs`, `POST /jobs/{id}/shortlist`, `POST /jobs/{id}/tailor`, `GET /jobs/{id}/cv` (PDF), `POST /jobs/{id}/edit`, `POST /jobs/{id}/approve`, `POST /jobs/{id}/apply`, `POST /crawl`, `GET /stats`, `WS /ws` (tiến độ realtime); **CV Studio:** `GET/PUT /cv/{scope}` (scope = `master` | job_id; JSON structured), `POST /cv/{scope}/compile` (→ PDF), `GET /cv/{scope}/versions`, `POST /cv/{scope}/rollback/{ver}`, `GET /cv/templates`.

**Auth**: local single-user (token đơn giản trong `.env`) — vì chạy local, không public.

---

## 6. Cải thiện Master CV hiện tại (workstream song song)

Rà soát nhanh `resume/*.tex` — các cải thiện đề xuất (làm ở Phase 1, không bịa nội dung):
- **Summary**: thêm 1 dòng định lượng impact; đồng bộ giọng văn với JD backend.
- **Skills**: đang comment nhiều dòng (Backend Frameworks, Frontend, Tools). Cân nhắc bật lại có chọn lọc để ATS bắt keyword (Spring Boot, FastAPI, Git, Docker...).
- **Experience/Project**: dùng cấu trúc **action verb + tech + kết quả định lượng** (đã khá tốt); chuẩn hoá thì động từ (past tense), thêm metric nơi có thật.
- **Honors**: "300+ LeetCode" ok; cân nhắc gom cùng chứng chỉ nếu có.
- **Master vs tailored**: giữ `resume/` làm **Master CV** (đầy đủ nhất); bản tailored sinh ra ở `out/<job_id>/`, không ghi đè Master.
- **Nhất quán ngày tháng**: tốt nghiệp Apr 2026; đảm bảo mọi mốc thống nhất.

> Chi tiết rewrite rule nằm ở `SKILL.md`.

---

## 7. Tech stack

| Layer | Lựa chọn | Lý do |
|---|---|---|
| Ngôn ngữ | **Python 3.11+** | Hệ sinh thái crawl (Playwright), Slack Bolt, LaTeX tooling. |
| Crawl | Playwright + playwright-stealth | Các site đều SPA, cần headless browser + chống anti-bot. |
| Web backend/API | **FastAPI** (REST + WebSocket) | Cùng Python với crawler/tailor; async; realtime cho dashboard. Chứa orchestrator. |
| Web frontend | **React (Vite + TS) + TailwindCSS + shadcn/ui** | UI/UX dashboard gọn, hiện đại; component sẵn cho bảng/kanban/form. |
| Charts | Recharts (theo skill `dataviz`) | Funnel, biểu đồ nguồn/ngày, KPI — palette nhất quán light/dark. |
| Store | **PostgreSQL** (JSONB) + Alembic | Quan hệ cho funnel/filter + JSONB cho JD; migrations. |
| Slack | slack-bolt (Socket Mode) | Kênh **phụ**: thông báo + thao tác nhanh. Không cần public URL. |
| LLM | **Claude API** (claude-opus-4-8 / sonnet) | Tailor CV + cover letter + gap analysis. |
| CV build | Docker `csmith/awesome-cv-builder` | Đã có sẵn, tái dùng. |
| Email | Gmail API hoặc SMTP | Kênh apply full-auto. |
| Config | `.env` + `config.yaml` | Secrets tách khỏi code. |
| Chạy local | `docker-compose` (Postgres) + `make dev` | 1 lệnh dựng Postgres + API + web. |

---

## 8. Cấu trúc thư mục (đề xuất)

```
CV_Template/
├── PLAN.md  SKILL.md  CLAUDE.md          # docs (file này)
├── cv.tex  awesome-cv.cls  fonts/  resume/  # Master CV (giữ nguyên)
├── docker-compose.yml  Makefile  pyproject.toml  .env.example  .gitignore
├── jobpilot/                                   # Python backend
│   ├── config.yaml  config.py  cli.py
│   ├── api/      main.py  routes/  ws.py  deps.py     # FastAPI (REST + WebSocket)
│   ├── crawler/  base.py itviec.py topcv.py vietnamworks.py normalize.py
│   ├── store/    db.py  models.py  migrations/  raw/  # SQLAlchemy + Alembic (Postgres)
│   ├── slack/    app.py  blocks.py  handlers.py        # kênh phụ
│   ├── tailor/   tailor.py  prompts.py  build.py  cover_letter.py
│   ├── apply/    dispatcher.py  email_apply.py  portal_apply.py
│   ├── orchestrator.py   cli.py
│   └── tests/
├── web/                                        # React frontend (Vite + TS)
│   └── src/  pages/ (Dashboard, Jobs, JobDetail, CvReview, Applications, Settings, Runs)
│            components/  api/  hooks/
└── out/<job_id>/  cv.tex  cv.pdf  cover_letter.pdf  meta.json   # bản tailored
```

---

## 9. Roadmap / Milestones

- **Phase 0 — Docs & setup** *(file này)*: PLAN, SKILL, CLAUDE + scaffolding, `.env.example`, config schema, `docker-compose` (Postgres).
- **Phase 1 — CV foundation**: cải thiện Master CV (§6); wrapper build PDF từ Python + verify Docker chạy được.
- **Phase 2 — Data + API skeleton**: Postgres schema + Alembic + SQLAlchemy models; FastAPI khung + `GET /jobs` + `GET /stats` + WebSocket.
- **Phase 3 — Crawler MVP**: ITviec trước → Job schema → Postgres + dedup (`id` và `(company,title)`). Sau đó TopCV, VietnamWorks, TopDev. Config `stacks` + sort freshness (🔥 <48h). Tier 2/ATS adapter (§5.1.1) để sau.
- **Phase 4 — Web Dashboard MVP**: React app — trang Dashboard (KPI+funnel), Jobs (filter/search), Job detail, chọn/shortlist job. Realtime qua WS.
- **Phase 4.5 — CV Studio**: import một lần `resume/*.tex` hiện tại → JSON structured (parse thủ công 1 lần, verify PDF build ra giống hệt); structured editor (JSON ⇄ Jinja2 → `.tex`) + compile-on-demand PDF (PDF.js) + version history cho **Master CV** trước. Sau đó: HTML live preview, theme gallery, raw LaTeX mode (Monaco).
- **Phase 5 — Tailor engine + CV Review**: Claude tailor (output = JSON structured như Studio dùng) + build + diff; trang CV Review (preview PDF + diff + Approve/Sửa/Bỏ, edit loop + nút "Mở trong CV Studio").
- **Phase 6 — Apply dispatcher + Applications board**: email full-auto (test email mình trước) → portal pre-fill; Kanban applications + error reporting.
- **Phase 7 — Slack (kênh phụ)**: mirror thông báo + nút nhanh (Chọn/Approve/Sửa/Nộp) đồng bộ cùng state.
- **Phase 8 — Orchestration & polish**: state machine end-to-end, job queue, cron tùy chọn, logging, Runs page.
- **Phase 9 — TopCV + VietnamWorks chạy thật**: parser schema.org `JobPosting` dùng chung, nhận diện field theo giá trị (`crawler/vietnam.py`).
- **Phase 10 — Tailor + apply rời request path**: `POST /tailor|edit|apply` trả 202 + task, tiến độ qua WS.
- **Phase 11 — Phân trang + nguồn tier-2**: `BaseScraper.search()` đi nhiều trang (`crawl.max_pages`) với guard "site bỏ qua `?page=`"; `FeedScraper` + `HttpFetcher` cho nguồn có feed chính thức; thêm WeWorkRemotely + Arbeitnow.
- **Phase 15 — Follow-up**: `apply/followup.py` + migration 0005. Nhịp nhắc hữu hạn (5 ngày làm việc → +7 → dừng), **không tự gửi**, dry run không được nhắc.
- **Phase 14 — Quality signals**: `crawler/quality.py` giải thích `match_score` bằng chính danh sách `stacks` và gắn cờ `no_jd`/`thin_jd`/`stale`/`undated` (chú thích, không lọc). `cli backfill` cho job cũ.
- **Phase 13 — ATS readability**: `cv/ats.py` đọc lại PDF như một applicant tracking system và báo đúng những gì parser không lấy lại được (không chấm điểm). Ưu tiên `pdfminer.six`; `pypdf` fallback tự khai báo không tin được về khoảng trắng.
- **Phase 12 — ATS adapter (tier 3)**: `crawler/ats.py` — Greenhouse + Lever qua board JSON API công khai; "một trang = một công ty"; thêm công ty = 1 từ trong `ats:` của config. `rank_hits` xếp hạng theo số từ khoá khớp để `limit` không bị tiêu vào job xa đề.

**Định nghĩa "xong" cho MVP demo (theo yêu cầu user)**: crawl ~10 job từ 3 site → hiện trên **Web Dashboard** (+ thông báo Slack) → user chọn → tailor → **review PDF+diff** (duyệt/sửa) → email/portal apply → báo lỗi nếu fail. Slack đồng bộ cùng state.

---

## 9.1 Roadmap mở rộng (Phase 18–25)

Roadmap §9 đã đóng ở Phase 17. Đợt mở rộng này đến từ việc khảo sát ba dự án cùng loại —
[ai-job-search](https://github.com/MadsLorentzen/ai-job-search),
[career-ops](https://github.com/santifer/career-ops),
[jobsync](https://github.com/Gsync/jobsync) — và câu hỏi đáng giá nhất mà cả ba đều trả lời
còn mình thì chưa:

> **Pipeline của JobPilot kết thúc ở `SUBMITTED`.** Nộp xong là mù. Không biết công ty nào
> trả lời, nguồn nào thực sự ra phỏng vấn, kênh nào chỉ tốn thời gian. Mọi câu hỏi dạng
> "cách tìm việc này có hiệu quả không" đều không có dữ liệu để dựa vào.

Cái mình đã hơn họ thì giữ nguyên — Postgres là single source of truth, dashboard realtime,
tailor index-based có guardrail 2 tầng, ATS text-layer check, robots.txt gate. Đợt này chỉ bê
**tính năng** về, không bê kiến trúc. Thứ tự dưới đây xếp theo **phụ thuộc dữ liệu**, không
theo độ hấp dẫn: phase sau cần dữ liệu do phase trước sinh ra.

| Phase | Nội dung | Xong nghĩa là |
|---|---|---|
| **18** | **Outcome tracking** — vòng đời sau `SUBMITTED`: `replied` / `interview` (nhiều vòng) / `offer` / `rejected` / `withdrawn` / `ghosted`. Bảng `application_events` append-only + cột `outcome_stage` denormalized. | Ghi/sửa/rút lại được outcome trên board; `GET /stats` trả cả "đang ở chặng nào" lẫn "đã từng tới chặng nào"; ghi outcome thì dừng follow-up. |
| **19** | **Inbox sync** — dùng lại `crawler/mailbox.py`, quét mail nhà tuyển dụng, ghép với application (domain công ty / thread / thời điểm nộp), Claude phân loại thư → **đề xuất** outcome. | Mail thật vào → đề xuất hiện trên board kèm trích đoạn; **user bấm xác nhận mới ghi**. Không đề xuất nào tự vào DB. |
| **20** | **Analytics thật** — reply rate / interview rate theo nguồn · kênh · level, time-to-first-reply, phát hiện tin đăng lại nhiều lần (ghost job). | Trang Dashboard trả lời được "nguồn nào đáng crawl tiếp"; mẫu nhỏ thì nói rõ là mẫu nhỏ, không hiện tỉ lệ ảo. |
| **21** | **LLM ranking 2 tầng + dealbreaker** — keyword score làm bộ lọc rẻ, Claude chấm rubric cho top N (fit / level / stack / location / growth) + cờ legitimacy; hard gate (lương sàn, ngôn ngữ, seniority, onsite); đếm token + chi phí mỗi lần chạy. | Chấm N job tốn đúng N request và **biết** hết bao nhiêu tiền; job vướng hard gate bị loại kèm lý do đọc được. |
| **22** | **Drafter–reviewer + chống prompt injection** — agent thứ hai soi lại bản tailor / cover letter (từ khoá sót, câu yếu) → một vòng sửa tự động trước khi tới người. JD được đối xử như **dữ liệu**, không phải chỉ thị. | JD có chèn câu ra lệnh không đổi được hành vi agent (có test ghim); reviewer note hiện trên trang CV Review. |
| **23** | **Vòng cắt CV cho vừa 2 trang** — quá trang thì bỏ/rút gọn item ít liên quan nhất theo thứ hạng relevance của tailor plan rồi build lại. Deterministic, không tốn thêm lượt LLM. | CV tailored không bao giờ tràn quá `cv.max_pages`; cái bị cắt được liệt kê ra chứ không biến mất im lặng. |
| **24** | **Interview prep + STAR story bank** — bộ chuẩn bị theo từng job, STAR map từ kinh nghiệm **thật** (guardrail như tailor), tích luỹ thành story bank dùng lại. | Ghi event `interview` là có nút sinh bộ chuẩn bị; mọi câu chuyện đều truy được về một mục có thật trong Master CV. |
| **25** | **Upskill** — gom gap của mọi job đã tailor: yêu cầu nào lặp lại mà mình thiếu → xếp hạng theo tần suất × mức độ gần. | Một danh sách ngắn "học cái này trước" dựa hoàn toàn trên job thật đã gặp, không phải lời khuyên chung chung. |

**Quyết định kiến trúc chốt trước, áp cho cả cụm 18–20:** outcome sống ở tầng
`Application`, **không** thêm giá trị vào enum `job_status`. `JobStatus` mô tả vòng đời
*trước khi nộp* của một *job*; một job `SUBMITTED` vẫn là `SUBMITTED` dù sau đó thành offer
hay bị từ chối. Thêm value vào Postgres enum còn kéo theo migration `ALTER TYPE` (không chạy
được trong transaction block), `web/src/lib/statuses.ts`, funnel, và `slack/events.py`.

---

## 10. Rủi ro & giảm thiểu

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Anti-bot (Cloudflare ITviec, hydration TopCV/VNW) | Cao | Playwright stealth, retry, rate-limit, chạy local IP thật, graceful per-site fail. |
| Site đổi DOM/API | Trung | Scraper tách riêng + test snapshot; cảnh báo khi 0 job. |
| CV bịa nội dung | Cao | Guardrail truthfulness (SKILL.md), diff bắt buộc user duyệt. |
| ToS/ban (LinkedIn) | Cao | **Không** scrape/auto-apply LinkedIn. Chỉ 3 site VN + human-in-the-loop. |
| Auto-send email sai người | Trung | Preview email trên Slack trước lần đầu; whitelist/kênh bật rõ ràng. |
| Secrets rò rỉ | Cao | `.env` (gitignore), không log token, không commit DB dump/`out/`. |
| CAPTCHA khi apply portal | Trung | Không tự vượt CAPTCHA; chuyển sang human-in-the-loop. |
| Web/API lộ ra ngoài | Trung | Chỉ bind `localhost`; token auth đơn giản; không expose Postgres port ra ngoài compose. |
| Lệch state giữa Web ↔ Slack | Trung | **1 nguồn sự thật = Postgres**; mọi action đi qua API; đẩy update realtime (WS + Slack message update). |

---

## 11. Câu hỏi mở (chốt dần khi triển khai)

1. Email apply gửi từ **Gmail API** (OAuth) hay **SMTP app-password**? (Gmail API sạch hơn, có sẵn MCP.)
2. Bộ lọc job: cứng theo config (level, skill, location) hay để Claude tự chấm điểm match?
3. Ngưỡng `match_score` tối thiểu để post lên Slack?
4. Cover letter: 1 template cố định hay Claude sinh tự do mỗi job?
5. ~~Có cần lưu lịch sử ứng tuyển (đã nộp công ty nào) để tránh nộp trùng?~~ → **Có.** Bảng
   `applications` đã chặn nộp trùng từ Phase 6; Phase 18 (§9.1) mở rộng thành lịch sử đầy đủ
   *sau* khi nộp (`application_events`), vì tránh nộp trùng chỉ là một nửa giá trị của việc
   nhớ mình đã nộp cho ai.
