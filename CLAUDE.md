# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này.

## Repo là gì

Hai lớp:
1. **CV Template** — bộ khung LaTeX [Awesome-CV](https://github.com/posquit0/Awesome-CV) (`awesome-cv.cls`, `fontawesome.sty`, `fonts/`), build bằng Docker. Repo **chỉ chứa khung**, không chứa CV nào.
2. **JobPilot (đang xây)** — agent crawl job (ITviec/TopCV/VietnamWorks) → quản lý qua **Web Dashboard local** (control plane chính; Slack là kênh phụ) → tailor CV → duyệt/sửa → apply hybrid. Stack: FastAPI + React + PostgreSQL. Xem `PLAN.md` (kiến trúc) và `SKILL.md` (logic tailor).

## Đọc trước khi làm

- `PLAN.md` — kiến trúc, data model, roadmap, quyết định đã chốt.
- `SKILL.md` — quy tắc tailor CV, **guardrail chống bịa**.
- File này — commands + conventions.

## Nguyên tắc bắt buộc (đọc kỹ)

1. **Truthfulness**: khi tailor CV, KHÔNG bịa skill/kinh nghiệm/metric. Chỉ nhấn mạnh/diễn đạt lại dữ kiện có thật. Chi tiết: `SKILL.md §0`.
2. **Human-in-the-loop**: mọi hành động gửi ra ngoài cần user Approve, trừ kênh **email** đã bật rõ. **Không** auto-apply LinkedIn. **Không** scrape LinkedIn.
3. **Không commit thông tin cá nhân**: Master CV (tên, email, SĐT, học vấn, kinh nghiệm…) sống trong bảng `cv_versions` của Postgres và đi ra/vào qua API (`GET/PUT /cv/{scope}`). Repo không chứa CV nào — DB mới thì `ensure_master()` tạo **CV rỗng** (`cv/skeleton.py`), user tự điền trong CV Studio hoặc `jobpilot cv import <file.json>`. `cv/sample.py` là CV **hư cấu** chỉ dùng cho test + demo, app không bao giờ seed từ đó.
4. **Không ghi đè Master CV**: bản tailored sinh ra ở `out/cv/<scope>/`, Master trong DB giữ nguyên.
5. **Tôn trọng ToS/robots.txt/rate-limit** khi crawl. Site nào fail thì log + chạy tiếp, không retry vô hạn.
6. **Secrets**: mọi token (Slack, Claude API, email) đặt trong `.env` (đã gitignore). Không log, không commit token, không commit `jobpilot.db`.

## Quy trình triển khai (phase-by-phase + Codex Review)

Triển khai theo phase trong `PLAN.md §9`. **Mỗi phase là một vòng khép kín:**

1. **Implement** trọn vẹn 1 phase (theo scope PLAN.md), verify chạy được (không chỉ dựa test).
2. **Summary for Codex Review** — xuất một tóm tắt chuẩn để user đưa Codex review, gồm:
   - *Scope*: phase nào, mục tiêu.
   - *Changes*: danh sách file thêm/sửa + vai trò.
   - *Key decisions*: quyết định kỹ thuật + lý do.
   - *How to verify*: lệnh chạy thử + kết quả kỳ vọng.
   - *Risks / follow-ups*: điểm cần lưu ý, nợ kỹ thuật.
3. **Chờ Codex** — user mang summary sang Codex.
   - ✅ Codex **approve** → sang bước 4.
   - ❌ Codex **có ý kiến** → sửa theo feedback, quay lại bước 2 (không push).
4. **Push git** — commit (message theo Conventional Commits) + push. Chỉ push **sau khi Codex approve**.
5. **Tiếp phase sau.**

Ràng buộc:
- **Không tự merge/nhảy phase** khi chưa có approve.
- Mỗi phase = 1 (hoặc vài) commit gọn, message rõ; kết thúc phase mới push.
- Branch làm việc: `feat/jobpilot` (giữ `main` sạch), trừ khi user yêu cầu khác.
- Cập nhật checklist "Trạng thái hiện tại" bên dưới sau mỗi phase.

## Commands

### Build CV (Master hoặc tailored)
```bash
# Windows PowerShell (tại thư mục chứa cv.tex)
docker run --rm -v ${PWD}:/work csmith/awesome-cv-builder
# Linux/macOS/WSL
docker run -u $UID:$GID --rm -v $PWD:/work csmith/awesome-cv-builder
# Output: cv.pdf
```

### JobPilot (khi đã scaffold — xem cấu trúc ở PLAN.md §8)
```bash
# --- Postgres: dùng bản cài sẵn trên máy (PostgreSQL 17 + pgAdmin 4) ---
# Tạo DB một lần:  psql -U postgres -c "CREATE DATABASE jobpilot;"
# rồi đặt trong .env:  DATABASE_URL=postgresql+psycopg://postgres:<pass>@127.0.0.1:5432/jobpilot
# (Hoặc `docker-compose up -d postgres` nếu muốn chạy Postgres trong Docker.)
alembic upgrade head                # migrate DB — tạo schema `jobpilot`
uvicorn jobpilot.api.main:app --reload   # API backend (REST + WebSocket) tại :8000
cd web && npm run dev               # Web Dashboard (Vite) tại :5173  ← control plane chính
python -m jobpilot.cli crawl        # crawl các nguồn đang bật → Postgres
python -m jobpilot.cli crawl --query "java spring" --limit 50   # scope 1 lần chạy
                                    # (hoặc dùng card "Crawl setup" ở trang Runs: chọn nguồn,
                                    #  gõ từ khoá — có gợi ý lấy từ Master CV — rồi Crawl now)
python -m jobpilot.cli cv seed      # tạo Master CV rỗng nếu chưa có (idempotent)
python -m jobpilot.cli cv import my-cv.local.json   # nạp CV có sẵn vào DB
python -m jobpilot.cli cv export my-cv.local.json   # backup CV từ DB ra file (gitignored)
python -m jobpilot.cli cv build     # render JSON → .tex → PDF ở out/cv/master/
python -m jobpilot.cli tailor <job_id>            # tailor CV cho 1 job (cần ANTHROPIC_API_KEY)
python -m jobpilot.cli tailor <job_id> --no-build # chỉ ra plan, không build PDF
python -m jobpilot.cli apply <job_id>             # nộp theo kênh (email/portal/external)
python -m jobpilot.cli apply <job_id> --open-portal   # portal: mở browser pre-fill (không tự submit)
python -m jobpilot.cli confirm-submit <job_id>    # xác nhận đã tự nộp xong (portal/external)
python -m jobpilot.cli slack        # (tùy chọn) Slack Bolt — kênh phụ; cần API đang chạy
pytest jobpilot/tests               # test
# tất cả trong 1 lệnh:
make dev
```

## Conventions

- **Ngôn ngữ code/comment**: English. Docs cho user (PLAN/SKILL) có thể tiếng Việt.
- **Python**: 3.11+, type hints, `ruff`/`black` nếu có. Mỗi scraper kế thừa `crawler/base.py:BaseScraper`.
- **LaTeX**: giữ cú pháp Awesome-CV; dùng macro có sẵn `\tech{}`, `\techfe{}`, `\cvsimpleentry`, `\cvitems`. Đổi màu chủ đạo trong CV Studio (`theme.color`), không sửa `.tex` tay.
- **Job schema**: mọi scraper phải normalize về `Job` schema chung (PLAN.md §3.1) để dedup theo `id = "<source>:<native_id>"`.
- **State**: **Postgres là nguồn sự thật duy nhất**; mọi thay đổi trạng thái đi qua API backend (Web và Slack cùng gọi API → không lệch state). Orchestrator idempotent (chạy lại không hỏng). Đẩy update realtime qua WebSocket (web) + update message (Slack).
- **Web/Frontend**: React + Vite + TS + TailwindCSS + shadcn/ui; charts theo skill `dataviz`, UI theo skill `frontend-design` (palette nhất quán light/dark, có cá tính riêng). Bind `localhost`, không expose ra ngoài. DB migrations bằng Alembic — đổi schema phải tạo migration, không sửa tay.
- **CV inline markup**: text trong `CvDocument` **không bao giờ** chứa LaTeX thô. Dùng subset markdown: `**bold**` → `\textbf`, `` `x` `` → `\tech`, `~x~` → `\techfe`, `[label](url)` → `\hreficon`. Mọi thứ còn lại được escape (`jobpilot/cv/latex.py`). Agent tailor (Phase 5) phải xuất đúng subset này.
- **CV data flow (quan trọng)**: nguồn sự thật của nội dung CV là **JSON structured** (CV Studio + agent tailor cùng dùng) → serialize ra `.tex` qua Jinja2 → Docker build PDF. Không sửa `.tex` tailored bằng tay ngoài luồng này (trừ raw-mode trong Studio, có cảnh báo mất round-trip). Mọi lần save = 1 row `cv_versions` (author = user|agent).
- **Verify thay đổi runtime**: sau khi sửa scraper/tailor/apply, chạy thử flow tương ứng và quan sát output thật, đừng chỉ dựa vào test. Sau khi sửa template Jinja2 hoặc `cv/latex.py` phải build lại PDF để chắc không lỗi LaTeX.

## LinkedIn qua Job Alerts (không crawl)

`linkedin.com/robots.txt` **cấm** truy cập tự động vào trang job — kể cả endpoint
`/jobs-guest/` khi không đăng nhập — và mở đầu bằng *"The use of robots or other
automated means to access LinkedIn without the express permission of LinkedIn is
strictly prohibited."* Nên **không có cách crawl LinkedIn nào tuân thủ robots.txt**,
và dự án không làm (nguyên tắc 5).

Thay vào đó dùng chính cơ chế LinkedIn cung cấp: **Job Alerts**. LinkedIn gửi job
khớp vào mail của bạn, JobPilot đọc **hộp mail của bạn**. Không request nào tới
LinkedIn, không tài khoản nào bị ban.

**Cài đặt:**
1. LinkedIn → Jobs → tìm theo tiêu chí → bật **Job alert** (nên tạo 5–10 alert, đặt *Daily*).
2. Bật 2-Step Verification cho Google, rồi tạo **App Password** tại
   <https://myaccount.google.com/apppasswords> (mật khẩu Gmail thường sẽ bị từ chối).
3. Điền `IMAP_USER` / `IMAP_PASSWORD` trong `.env`.
4. Bật nguồn: `sources: - { key: linkedin, enabled: true }` trong `config.yaml`
   (hoặc bấm trên trang Settings).
5. `python -m jobpilot.cli run` — hoặc bấm **Crawl now** ở trang Runs.

**Giới hạn thật:** mail alert có title/company/location nhưng **không có JD đầy đủ**.
Job vào DB với cờ `needs_jd`; mở trang job, dán JD vào rồi mới tailor — nếu không
agent chẳng có gì để bám. Kênh apply luôn là `external`: bạn tự nộp trên LinkedIn.

**Đã verify trên mail thật** (1.116 alert trong hộp thư): parser đọc đúng title/company/
location/job-id. Hai bug chỉ lộ ra khi chạy thật, đã sửa + có test giữ:
LinkedIn để **company và location trên CÙNG một dòng** ngăn bằng `·` (không phải 2 dòng),
và dòng social proof (`34 company alumni`, `4 connections`) lọt vào `location`.

**Đường thứ hai:** nút **Add job** ở trang Jobs — dán thẳng link + JD. Dùng cho job
thấy ngoài alert. Link LinkedIn cho ra id ổn định nên dán lại cùng link sẽ *update*
chứ không tạo bản trùng.

## Thêm một site crawl mới

1. Tạo `crawler/<site>.py` kế thừa `BaseScraper`, cài `search()` + `parse_detail()`.
2. Normalize output về `Job` schema; set `apply_channel`/`apply_target`.
3. Thêm rate-limit + đọc robots.txt; test với snapshot HTML để tránh phụ thuộc mạng.
4. Đăng ký site trong `config.yaml`.

## Trạng thái hiện tại

- ✅ Khung LaTeX Awesome-CV hoạt động (`awesome-cv.cls` + `fonts/`, build Docker). Nội dung CV nằm trong DB, không trong repo.
- ✅ Docs nền tảng: `PLAN.md`, `SKILL.md`, `CLAUDE.md`.
- ✅ **Phase 0** — scaffold `jobpilot/` + `web/` (placeholder) + `docker-compose` + `pyproject` + `Makefile` + `config.yaml`/`.env.example` + config loader + CLI + smoke tests.
- ✅ **Phase 1** — Python build wrapper (`tailor/build.py` + `cli build`, Docker LaTeX, page-count qua pypdf) + cải thiện Skills của Master CV (ATS, giữ 1 trang) + untrack LaTeX aux cũ.
- ✅ **Phase 2** — Data + API skeleton: SQLAlchemy 2.0 models (`store/models.py`: jobs/applications/edits/runs/cv_versions + `JobStatus` enum) + engine/session (`store/db.py`, sync psycopg3, schema `jobpilot`, SQLite translate-map cho test) + Alembic (initial migration, GIN trên payload) + FastAPI (`api/main.py`: `GET /jobs`, `GET /jobs/{id}`, `GET /stats`, `WS /ws`, token auth, CORS localhost) + `cli serve`. 25 test pass; verify live HTTP+WS trên SQLite; migration render Postgres DDL hợp lệ (Docker chưa chạy nên chưa `alembic upgrade` lên Postgres thật).
- ✅ **Phase 3** — Crawler MVP: `crawler/` framework (`base.BaseScraper` template + pure `search_url`/`parse_search`/`parse_detail`; `fetch.PlaywrightFetcher` lazy import; `ratelimit` jittered delay; `robots` policy; `text`/`normalize` HTML→md + posted_at + level + match_score; `persist` upsert-by-id + cross-source dedup `(company, normalized_title)`; `pipeline.run_crawl` graceful per-site fail + `Run` record; `registry` config→scrapers). ITviec scraper implemented (real selectors); TopCV/VietnamWorks scaffolded to the same interface (disabled in config until real HTML snapshot); `FixtureScraper` for offline e2e. `cli crawl` wired (`--query`, `--no-robots`). No schema change (payload holds §3.1). 52 tests pass; verified live crawl→persist→Run on SQLite via fixture + real CLI path (ITviec fails gracefully w/o Playwright).
- ✅ **Phase 4** — Web Dashboard MVP: React (Vite+TS+Tailwind, shadcn-style hand-rolled UI) "flight deck" dashboard. Backend additions: `POST /jobs/{id}/shortlist|skip` (state transitions + WS `job_updated` broadcast), stats enriched (`fresh`, `by_level`, `by_day`), `/jobs` search (`q`) + `fresh` filter, `JobDetailOut` (skills/description_md/is_fresh from payload), shared `timeutil` (+07 fixed offset). Frontend: Dashboard (KPI cards + signature "approach funnel" + BySource/ByDay charts via validated dataviz palette), Jobs (filter/search + shortlist/skip inline), Job detail (JD + skills + actions), realtime via `useWebSocket` (LIVE indicator + auto-refetch), dark/light theme. 58 py tests pass; `npm run build` clean (tsc+vite); verified live over HTTP (seeded SQLite → serve → curl /stats, /jobs, detail, q+fresh, shortlist transition, 401).
- ✅ **Phase 4.5** — CV Studio (slice lõi): `jobpilot/cv/` — `schema.py` (Pydantic `CvDocument`: theme/header/sections discriminated union paragraph|bullets|education|experience|projects), `latex.py` (inline markup `**bold**`/`` `tech` ``/`~techfe~`/`[label](url)` + escape mọi ký tự LaTeX đặc biệt — content không bao giờ chứa LaTeX thô), `templates/awesome_cv/*.j2` (Jinja2, delimiter `<< >>`/`<% %>`), `render.py` (JSON → `cv.tex` + `resume/*.tex` + `tex_snapshot`), `master_seed.json` (import 1 lần từ `resume/*.tex` — **PDF text identical** với `cv.pdf` gốc), `store.py` (`cv_versions` append-only, auto-seed master, rollback = re-save, `fork_from_master` cho Phase 5), `compile.py` (build dir riêng `out/cv/<scope>/`, không đụng `resume/`). API: `GET/PUT /cv/{scope}`, `POST /cv/{scope}/compile`, `GET /cv/{scope}/pdf`, `GET /cv/{scope}/versions[/{v}]`, `POST /cv/{scope}/rollback/{v}`, `GET /cv/templates` + WS `cv_updated`/`cv_compiled`. CLI `cv seed|render|build|versions`. Web: trang **CV Studio** (editor structured — reorder/toggle section, bullet/entry/tag inputs — + PDF preview compile-on-demand + version history/restore). 115 py tests pass; `npm run build` clean; verified live: auto-seed → edit (đổi position, đưa Skills lên, ẩn Honors) → PUT v2 → Docker compile → PDF phản ánh đúng 3 thay đổi → rollback v1 → PDF **identical** với Master gốc → WS push.
- ✅ **Phase 5** — Tailor engine + CV Review: `jobpilot/tailor/` — `schema.py` (`TailorPlan` **index-based**: agent chỉ được reorder/drop/ẩn theo chỉ số của Master CV; free text duy nhất là `summary` → bịa skill là *shape schema không diễn đạt được*, không phải luật để agent tuân theo), `guard.py` (2 tầng: structural — mọi index phải trỏ vào content có thật; lexical — mọi token "trông như tech" trong summary phải có trong vocabulary của Master CV; trả về violations để engine retry 1 lần), `prompt.py` (system prompt encode SKILL.md §0/§2 + Master CV render thành **indexed outline** = address space của plan; system ổn định/user volatile để cache tốt), `engine.py` (`claude-opus-4-8`, adaptive thinking, structured output qua `messages.parse(output_format=TailorPlan)`, 1 vòng retry khi vi phạm guardrail; `FixtureEngine` cho test), `apply.py` (plan → tailored `CvDocument`, thuần & không mutate Master), `diff.py` (structural diff: rewritten/trimmed/hidden/reordered — không dùng line diff vì tailor chủ yếu *di chuyển* content), `service.py` (state machine SHORTLISTED→TAILORING→REVIEW→APPROVED/SKIPPED, edit loop có cap `edit_max_rounds`, `Run` record, lưu plan+diff vào `cv_versions.meta`). Migration **0002** thêm `cv_versions.meta`. API: `POST /jobs/{id}/tailor|edit|approve|reject`, `GET /jobs/{id}/review|cv` (router `review` phải include **trước** `jobs` vì `GET /{job_id:path}` là greedy) + WS `tailor_done`. CLI `tailor`. Web: trang **CV Review** (PDF tailored | diff + gap report + edit box), CV Studio nhận scope `/cv/:scope`. 186 test pass; verify live qua HTTP với Docker build thật (chỉ giả lệnh gọi Claude): plan→PDF 1 trang phản ánh đúng 4 thay đổi, facts/metrics giữ nguyên, Master CV không đổi, edit round + approve + 409/422 đúng, **guardrail chặn plan bịa "Apache/Terraform" ở tầng HTTP và không ghi CV nào**.
- ✅ **Phase 6** — Apply dispatcher + Applications board: `jobpilot/apply/` — `letter.py` (cover letter SKILL.md §2 bước 4; **tách `paragraphs` (claim, check nghiêm ngặt theo vocabulary Master CV) khỏi `learning_note` (chỗ DUY NHẤT được nhắc skill MISSING, và chỉ những MISSING mà tailor plan đã xác định)** → câu "chưa dùng X, sẵn sàng học" diễn đạt được còn "thạo X" thì không), `email.py` (**3 gate độc lập**: `enabled` → `dry_run` → `test_recipient`; `build_email` thuần không chạm socket, `send_email` là hàm duy nhất nói chuyện với mail server và từ chối khi dry_run; MIME + đính kèm PDF qua stdlib `smtplib`), `portal.py` (handoff package: URL + CV + field để paste, luôn chạy được không cần Playwright; `match_field` so khớp **theo từ** — `prefill_with_browser` chỉ nối vào CLI, không bao giờ tự submit), `dispatcher.py` (email full-auto | portal/external chờ user confirm; **dry run giữ job ở APPROVED** vì không có gì được gửi; mọi nhánh đều ghi `Application` + `Run`). Migration **0003** thêm `applications.meta` + `created_at`. API `POST /jobs/{id}/apply|confirm-submit|report-failure`, `GET /applications[?result=]`, `GET /applications/settings` + WS `apply_done`. CLI `apply` / `confirm-submit`. Web: trang **Applications** (4 cột Prepared/Your turn/Submitted/Failed + banner trạng thái gate) + nút Apply ở CV Review. 232 test pass; verify live: dựng **SMTP server thật tại chỗ** → dry run không gửi & giữ APPROVED → bật gate → gửi thật, message bắt được có đúng recipient test, cover letter làm body, câu gap còn nguyên, và **PDF đính kèm byte-identical với bản tailored**; portal không tự submit; config mặc định (`enabled: false`) chặn gửi ở tầng HTTP.
- ✅ **Phase 7** — Slack (kênh phụ): `jobpilot/slack/` — **Slack là client thuần của REST API, backend không biết gì về Slack** (PLAN.md §10: 1 nguồn sự thật = Postgres, mọi action đi qua API → Web và Slack không thể lệch state). `client.py` (`JobPilotClient` gọi REST; nhận inject `httpx.Client` nên test chạy thẳng vào ASGI app thật), `blocks.py` (Block Kit builders **thuần**, không import SDK; `check_blocks` validate đúng limit Slack — 50 blocks / 3000 char section / 75 char label / 2000 char value; builder truncate thay vì để Slack trả 400), `events.py` (WS event → tin nhắn; **cố tình im lặng** với các transition thường để channel còn dùng được — chỉ post review/apply/failure), `app.py` (Socket Mode; nút = dispatch table `ACTIONS` → method của client; mirror WS chạy thread riêng, tự reconnect; degrade rõ ràng khi thiếu SDK/token). CLI `slack --api --web`. 256 test pass; verify live: client drive toàn bộ funnel qua HTTP thật (shortlist→tailor→approve→apply→confirm-submit), render đúng job/review/apply card (gap "Apache Kafka" hiện rõ, portal card có đủ field để dán), WS thật đẩy 2 event → mirror lọc còn 1 notification. **Chưa verify được: gửi thật lên Slack workspace** (chưa có token/app).
- ✅ **Phase 8** — Orchestration & polish: `orchestrator.py` — `TaskQueue` in-process (ThreadPoolExecutor **1 worker**: máy chạy Docker + browser cùng lúc thì fan-out chỉ tranh tài nguyên, và serial làm chữ "queued" có nghĩa; mỗi task body tự mở session DB riêng vì session SQLAlchemy không thread-safe). Worker thread đẩy progress về event loop của API qua `run_coroutine_threadsafe` → WS `task_updated`. **Invariant**: `status` được ghi *cuối cùng* (sau `result`/`finished_at`) vì đó là tín hiệu mọi consumer poll; eviction history không bao giờ xoá task chưa chạy xong. `POST /crawl` → 202 + task (chặn crawl thứ 2 khi đang chạy: sẽ đua rate-limit cùng site), `GET /tasks[/{id}]`, `GET /runs`, `GET/PUT /settings`. **Settings ghi vào `config.local.yaml` (gitignored) merge đè lên `config.yaml`** — vì comment trong `config.yaml` là tài liệu (nhất là 3 cổng an toàn email) và YAML round-trip sẽ xoá sạch; patch không validate được thì bị từ chối *trước khi ghi*. CLI `run [--query] [--every N]` (loop đơn giản thay vì thêm dependency scheduler; rc=1 khi mọi site fail để cron thấy được). Web: trang **Runs** (queue realtime + history + nút Crawl) và **Settings** (crawl/sources/apply gates/CV, mỗi card save riêng). 279 test pass; verify live: `POST /crawl` → 202, crawl thứ 2 → 409, WS stream `queued→running(progress)→done` với `finished_at`+`result` đầy đủ, site fail được báo chứ không nuốt, settings round-trip mà `config.yaml` **byte-identical**, patch sai bị từ chối, và crawl thật (không có Playwright) fail có thông báo hành động được + vẫn ghi `Run`.
### Nợ kỹ thuật còn lại (roadmap PLAN.md §9 đã xong)

- **Crawler**: ITviec + LinkedIn(alerts) chạy thật; TopCV/VietnamWorks/TopDev mới là scaffold (disabled trong config). Trang Runs chỉ cho chọn nguồn `enabled && ready` — `ready` = có scraper đăng ký trong `registry.SCRAPERS`, vì bật trong Settings không có nghĩa là đã implement. Cần `pip install -e '.[crawler]' && playwright install chromium` để crawl.
- **Bài học selector (ITviec)**: ITviec dùng utility CSS nên **match class theo substring là bẫy** — `[class*=city]` khớp `opa-city-50` khiến mọi job có location `"Hiring"`, `[class*=salary]` bắt trúng banner "IT Salary Report". Location/posted/salary giờ nhận diện **theo giá trị** (danh sách thành phố, regex thời gian), không theo cấu trúc. ITviec giấu lương sau login → `salary=None` là câu trả lời đúng, không phải placeholder. Test `test_itviec.py` ghim đúng các bẫy này.
- **Fetch strategy**: `PlaywrightFetcher` load bằng `domcontentloaded` rồi *cố* chờ `networkidle` trong 6s và bỏ qua nếu timeout. Chờ `networkidle` như điều kiện load là bẫy: job board chạy analytics/socket không bao giờ im, trang render xong nhưng `goto` treo tới timeout rồi fail cả crawl (đúng lỗi ITviec gặp).
- **Tailor/apply vẫn chạy đồng bộ** trong request (~30–60s). `TaskQueue` đã có sẵn và generic — chuyển sang background chủ yếu là việc của frontend (poll/WS thay vì await response).
- **CV Studio**: chưa có HTML live preview, theme gallery, raw LaTeX mode (Monaco), diff giữa 2 version bất kỳ. `tex_snapshot` đã lưu mỗi version nên diff làm sau rất nhẹ.
- **Cover letter** mới ở dạng text (dùng làm body email); chưa render `.tex`/PDF như SKILL.md §2 mô tả.
- **Chưa verify được** (thiếu credential, không phải thiếu code): gọi Claude thật (cần `ANTHROPIC_API_KEY`), gửi lên Slack workspace thật (cần Slack app + 3 token).
- **Đã verify trên môi trường thật**: `alembic upgrade head` chạy sạch 3 migration lên **PostgreSQL 17 local** (schema `jobpilot`, GIN index, enum `job_status` đầy đủ); toàn bộ 8 trang web chạy trên Postgres thật, không lỗi console; Compile PDF từ CV Studio và tailor→PDF đều qua Docker LaTeX thật.
- **Lưu ý khi chụp/screenshot UI**: headless Chrome **không có PDF viewer**, nên khung preview PDF sẽ trống (`net::ERR_ABORTED` trên blob URL). Đó là giới hạn của headless chứ không phải bug — chạy `headless=False` để kiểm tra thật.
- **Gmail OAuth** chưa làm — dùng `method: smtp` (Gmail app password chạy được).

## Quyết định đã chốt (không tự đổi nếu user không yêu cầu)

- Apply = **hybrid theo kênh** (email full-auto, portal/LinkedIn human-in-the-loop).
- Nguồn = **ITviec + TopCV + VietnamWorks** lõi (pluggable, mở rộng theo tier — PLAN.md §5.1.1); không LinkedIn/Facebook.
- Giao diện = **Web Dashboard local** là chính, **Slack** phụ. DB = **PostgreSQL**.
- Chạy = **local**, tay hoặc cron nhẹ.
- Stack = Python (FastAPI + Playwright stealth + Claude API + Docker LaTeX) + React(Vite/TS/Tailwind/shadcn) + PostgreSQL + slack-bolt.
