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
                                    # query NGẮN thôi: nó thành slug/từ khoá ở từng
                                    # site, "java spring boot backend" → TopCV 0 job.
                                    # limit > 1 trang thì `crawl.max_pages` quyết định
                                    # đi thêm bao nhiêu trang (mặc định 5).
                                    # (hoặc dùng card "Crawl setup" ở trang Runs: chọn nguồn,
                                    #  gõ từ khoá — có gợi ý lấy từ Master CV — rồi Crawl now)
python -m jobpilot.cli backfill     # gắn quality signal cho job crawl trước Phase 14 (idempotent)
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

0. **Đọc `robots.txt` TRƯỚC KHI viết code** (nguyên tắc 5). Nếu site cấm trang job
   thì dừng — không có cách nào "lách" cho hợp lệ (xem LinkedIn ở trên).
1. **Tìm `<script type="application/ld+json">` có `@type: JobPosting` trước đã.**
   TopCV và VietnamWorks đều có, và đó là target tốt nhất: JD đầy đủ, `datePosted`
   tuyệt đối, và site có động lực giữ nó đúng (Google Jobs index dựa vào đó) —
   mạnh hơn mọi động lực giữ tên class CSS. Dùng `crawler/jsonld.py`, không viết lại.
2. Tạo `crawler/<site>.py` kế thừa `BaseScraper`: `search_url()` + `parse_search()`
   + `parse_detail()`, tất cả **thuần** (HTML string → data, không network).
3. Nhận diện field **theo giá trị**, dùng `crawler/vietnam.py` (city / "thoả thuận"
   / posted / noise). Đừng match class theo substring — xem "Bài học selector".
4. `native_id` lấy từ **URL**, không bao giờ từ JSON-LD `identifier` (đó là id của
   *nhà tuyển dụng*: mọi job cùng công ty sẽ chung 1 row). Strip query tracking.
5. Normalize output về `Job` schema; set `apply_channel`/`apply_target`.
6. Test bằng snapshot HTML thật đã trim, ghim đúng các bẫy đã gặp (badge lẫn vào
   title, social proof lẫn vào location, "negotiable" thành salary).
7. Đăng ký trong `crawler/registry.SCRAPERS` + 1 dòng `config.yaml`.
8. **Crawl thật một lần** rồi đọc output — test xanh không có nghĩa là parser đúng.

**Nguồn có feed chính thức (RSS/JSON) thì kế thừa `crawler/feed.FeedScraper`**, đừng
viết lại: nó set `needs_detail = False` (feed đã có JD đầy đủ → 25 job = 1 request,
không phải 26), chọn `HttpFetcher` thay vì browser, và lo phần lọc theo query ở
`matches_query` (feed không có search phía server). Lọc theo **title + tag của site**,
không bao giờ theo JD — JD nào cũng nhắc nửa ngành công nghệ ở mục "nice to have".

**Đọc HẾT `robots.txt`, đừng `head -40`.** Jobicy để `Disallow: /api/` ở **dòng 48**;
40 dòng đầu trông rất thoáng. Cách duy nhất đáng tin là chạy chính
`RobotsPolicy(DEFAULT_USER_AGENT).allowed(url)` — nó parse cả file, và nó là thứ
sẽ chặn lúc crawl thật.

### Nguồn tier-2 đã loại (đừng kiểm tra lại từ đầu)

| Nguồn | Lý do loại |
|---|---|
| **Remotive** | `robots.txt`: `Disallow: /api/*` — mà API là đường duy nhất dùng được. |
| **Jobicy** | `robots.txt` dòng 48: `Disallow: /api/`. Filter `tag=` chạy rất tốt, `appliedFilters` còn echo lại — nhưng robots cấm thì dừng (nguyên tắc 5). |
| **RemoteOK** | `Content-Signal: ai-train=no, use=reference` + `User-agent: ClaudeBot → Disallow: /`. **Giống hệt TopDev** → cần một quyết định rõ ràng, không mặc định làm. |
| **Himalayas** | robots OK, nhưng API **bỏ qua mọi filter** (thử `q`/`search`/`keyword`/`skill`/`category`/`title` → `totalCount` y hệt 96.394 và cùng job đầu) và **âm thầm cắt `limit` xuống 20**. Feed newest-first đủ mọi ngành: 2/20 title là phần mềm → crawl "thành công" và giao job bác sĩ X-quang. |

Bài học chung: một API trả 200 kèm filter bị bỏ qua **nguy hiểm hơn** một API trả lỗi.
Nếu response có field kiểu `appliedFilters` thì **check nó**, đừng tin.

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
- ✅ **Phase 9** — TopCV + VietnamWorks chạy thật (hết scaffold): `crawler/jsonld.py` — parser schema.org **`JobPosting`** dùng chung, vì cả 2 site đều nhúng block đó cho Google Jobs và **nó là target ổn định nhất**: có JD đầy đủ, `datePosted` tuyệt đối, và site có động lực giữ nó đúng (index Google phụ thuộc vào đó) mạnh hơn động lực giữ tên class CSS. `crawler/vietnam.py` — nhận diện theo giá trị dùng chung (CITIES, "thoả thuận/thương lượng" → `salary=None`, regex posted, lọc noise "+3"/"Rất đông ứng viên"); `itviec.py` refactor để dùng chung, không còn 3 bản copy danh sách thành phố. **TopCV**: KHÔNG phải Vue SPA — server-rendered, curl là đủ; card `.job-item-search-result` + `data-job-id`. **VietnamWorks**: `__NEXT_DATA__` chỉ chứa dropdown filter, job đến từ XHR → **phải qua Playwright**; đọc DOM (`.new-job-card`) chứ không gọi API nội bộ `ms.vietnamworks.com` (host đó không có robots.txt; trang user-facing thì `robots.txt` cho phép rõ ràng — nguyên tắc 5). 354 test pass; **verify live cả 3 site**: TopCV 4/4 job Java thật (match 0.5–1.0, JD 2.4–3.1k chars), VNW 2/4 insert (2 bị filter đúng luật), ITviec không regress sau refactor.

  **Helper dùng chung nay ở `crawler/text.py`**: `el_text`, `first_match`, `strip_query`, `leaf_texts` — trước đó `_text` bị copy ở 4 file, `_clean_url`/`_first` ở 2 file.

  **8 bug chỉ lộ ra khi chạy thật hoặc khi review, đều đã có test ghim:**
  1. `/tim-viec-lam-it?keyword=java` **im lặng bỏ qua `keyword`** — trả 200 + 50 card của category IT chung (1.655 job: "IT Support", "IT Comtor"), rồi **cả 4/4 bị filter vì match_score = 0**. Search thật là slug trong path: `/tim-viec-lam-java-spring-boot` → 84 job Java. Param bị bỏ qua *tệ hơn* lỗi: crawl báo thành công và lặng lẽ giao sai job.
  2. JSON-LD `identifier` là id của **nhà tuyển dụng**, không phải job (TopCV: 198409 = id trong URL công ty). Dùng làm `native_id` thì mọi job cùng công ty chung 1 row và mỗi lần crawl ghi đè lần trước. `native_id` luôn lấy từ URL.
  3. `select_one("h2 a, a")` chọn theo **thứ tự document**, không theo thứ tự selector — link logo VNW đứng trước `h2 a` nên title lặng lẽ đến từ sai element. Dùng `text.first_match(root, *selectors)`.
  4. TopCV có 3 nhóm tag markup y hệt nhau; lấy hết thì "Team building"/"Bảo hiểm xã hội" thành **skill**, chảy vào `match_score` và gap report của tailor. Chỉ đọc nhóm "Chuyên môn".
  5. `SearchHit.extra` **không tự chảy sang `RawJob`** — `normalize` chỉ spread `raw.extra`. Đặt extra trên hit rồi quên `extra=dict(hit.extra)` trong `parse_detail` là mất sạch (TopCV mất label kinh nghiệm ở mọi job) *mà test cấp-card vẫn xanh*. `linkedin.py` đã làm đúng từ trước.
  6. Match city bằng substring không phân biệt hoa/thường: `"remote" in "remote debugging"` → tag skill thành **location**. Sai dữ liệu *trông như đúng*, tệ hơn thiếu dữ liệu. Giờ city phải **chiếm gần hết** label (bỏ tên city ra chỉ còn filler "TP."/"City"/dấu câu), và mọi phần tách bởi dấu phẩy đều phải là city → giữ "Hà Nội, Hồ Chí Minh", loại "Java, Remote debugging".
  7. Hard-stop khi thấy chữ "competitive/thoả thuận" **ăn mất lương thật** đứng sau nó ("Competitive salary package" rồi mới tới "$2,000 - $3,000"). Chỉ **login wall** mới stop scan (đúng ca ITviec, để không nhặt số từ banner "IT Salary Report"); "negotiable" chỉ là *leaf này không có lương*, tiếp tục quét.
  8. Regex posted bắt buộc có "ago"/"trước" → card render duration trần ("8 hours") bị mất timestamp, job mới trông như không có ngày. Suffix giờ là optional.

  **Crawl 0 job giờ có cảnh báo** (`base.crawl`): selector chết trả `[]` và crawl "thành công" với 0 job — không phân biệt được với query không có kết quả (PLAN §10 "cảnh báo khi 0 job"). Có cả cảnh báo khi `hits < limit` (VNW lazy-load).

- ✅ **Phase 11** — Phân trang + nguồn tier-2: `base.BaseScraper.search()` đi **nhiều trang** thay vì 1 fetch (`search_url(query, page)`, `crawl.max_pages` mặc định 5). Dừng ở cái đến trước: đủ `limit`, hết `max_pages`, trang rỗng, `search_url` trả URL trùng/`""`, hoặc **trang lặp lại id đã thấy**. Cái cuối là cái gánh: site *nhận* `?page=2` rồi bỏ qua sẽ trả lại trang 1 — không dedup xuyên trang thì crawl gom cùng 10 job 5 lần và báo cáo một "deep sweep" thành công (đúng họ với bug `?keyword=` của TopCV). Hook mới: `needs_detail` (feed đã đủ JD → không fetch detail) và `matches_query` (feed không có search phía server). `fetch.HttpFetcher` (httpx thuần) cho nguồn phục vụ *document* chứ không phải *app* — browser không chỉ chậm mà **làm hỏng JSON**: Chromium bọc response thành `<html><body><pre>…`. `crawler/feed.py` = `FeedScraper` + `parse_rss_items` (stdlib XML: RSS là XML, parser HTML sẽ "sửa" tag hỏng thay vì báo) + `parse_json_feed` (lỗi có kèm 80 byte đầu → nhận ra ngay là trang lỗi HTML hay JSON bị bọc `<pre>`). **2 nguồn tier-2 mới**: `weworkremotely.py` (RSS mỗi category = 1 "trang"; `<title>` là `"Company: Job Title"` → tách ở `": "` **đầu tiên**) và `arbeitnow.py` (JSON, `?page=` phân trang thật). Config: `crawl.max_pages` + 2 dòng source; Settings page có ô "Max pages per site". 428 test pass; **verify live cả 6 nguồn qua API + Postgres 17 thật**: WWR 8 job (JetBrains/Stripe/Reddit/Coinbase, JD 3.5–8.7k chars), Arbeitnow 9 job Java thật, 9 row vào DB với `posted_at` đủ 9/9 và JD đủ 9/9, re-crawl idempotent (updated=9, inserted=0), settings round-trip mà `config.yaml` **byte-identical**.

  **6 bug chỉ lộ ra khi chạy thật (test xanh suốt), đều đã có test ghim:**
  1. **`config.local.yaml` xoá sổ nguồn mới.** `deep_merge` ghi đè list, mà trang Settings ghi **cả danh sách `sources`** như lúc save. Máy nào đã mở Settings một lần là 2 nguồn tier-2 **không tồn tại** — không phải "tắt sẵn" mà *vắng mặt*, nên chính trang Settings cũng không hiện để bật. Giờ `config.yaml` giữ **danh mục**, overlay chỉ mang **tuỳ chọn theo key** (`config.merge_sources`).
  2. **Trang chặn anti-bot parse ra 0 hit → bị đọc là "hết kết quả".** Request thứ 2 tới TopCV trong cùng session trả Cloudflare "Sorry, you have been blocked", và crawl ghi "end of results" rồi đi tiếp — một lời nói dối. `PlaywrightFetcher` giờ **raise theo status code** (như `HttpFetcher` vẫn làm), nên 403 thành "page 2 failed (blocked — anti-bot), keeping 50 hit(s)". Lợi ích thật sự lớn hơn log: trước đây trang 403 vẫn được *parse* thành RawJob rỗng rồi ghi vào DB.
  3. **Trang không có job hợp lệ ≠ hết trang.** Arbeitnow trang 3 có 100 job, 0 cái khớp "Java" — vòng lặp dừng ở đó. Nhưng trang 4 và 5 mỗi trang có 1 job Java thật (JOIN, Doctolib). Tách hai câu hỏi: "site có sang trang không" (so `page_ids` với id đã thấy) khác "mình có muốn gì trên trang này không". Sau khi sửa: 7 → **9 job**.
  4. **TopCV trả 0 kết quả nhưng vẫn đổ 50 card gợi ý vào đúng container `.job-list-search-result`.** Query mặc định "Java Spring Boot Backend" (3 stack đầu) → slug 4 từ → `"Tuyển dụng 0 việc làm"` + 50 job **kế toán/QC/sale**. Không có cách nào phân biệt bằng cấu trúc, nên đọc **số đếm trong `<h1>`**; 0 thì trả `[]` + cảnh báo "try a shorter query". Không có số đếm = *không biết*, vẫn tin card (nếu TopCV đổi chữ thì không tự nhiên crawl 0 job mãi).
  5. **`infer_level` match substring**: "intern" nằm trong "internal"/"international", "lead" trong "leadership" — job senior của Stripe bị ghi **`level=intern`**. Sai dữ liệu *trông như đúng*, chảy thẳng vào chart by_level và bộ lọc. Giờ match theo **từ**; và riêng "intern" trần chỉ tính trong **title** — trong JD nó là từ thường (tiếng Đức "beraten wir uns intern", gặp thật trên Arbeitnow), còn "internship"/"thực tập" thì rõ nghĩa ở đâu cũng được.
  6. **`parse_posted_at` không đọc được ngày của feed.** RSS dùng RFC-822 ("Wed, 22 Jul 2026 07:00:51 +0000"), JSON API dùng unix epoch — cả hai đều rơi về `None`. Nguồn feed mà mất `posted_at` thì **không bao giờ được gắn 🔥 <48h** và biến mất khỏi chart by-day, tức là mất đúng thứ khiến feed đáng dùng. Epoch chỉ nhận 9–11 chữ số: `int()` không chặn sẽ đọc "2026" thành tháng 1/1970 — một câu trả lời sai tự tin, tệ hơn "không biết".

- ✅ **Phase 12** — ATS adapter (tier 3): `crawler/ats.py` — `AtsScraper` (base) + `GreenhouseScraper` + `LeverScraper`. **Một adapter phủ mọi công ty dùng nền tảng đó**, nên thêm công ty = thêm 1 từ trong `ats:` của `config.yaml`, không thêm code. Ý tưởng then chốt: **"trang" ở đây là một công ty** — vòng lặp phân trang Phase 11 hỏi `search_url(query, page)` rồi dừng khi hết URL, tức là "đi lần lượt các board đã khai báo". Không phải sửa gì trong vòng lặp; chỉ override `max_pages` vì `crawl.max_pages` sinh ra để chặn board *vô hạn*, còn danh sách công ty đã hữu hạn sẵn. `robots` kiểm bằng chính `RobotsPolicy` (không đọc bằng mắt): Greenhouse chỉ cấm `/embed/`, Lever `Allow: /` + `Crawl-delay: 1` (rate limiter 2–5s đã vượt). **Ashby cố tình không làm**: `api.ashbyhq.com` không phục vụ robots.txt (401) trong khi `jobs.ashbyhq.com` cấm `/api/` — đúng hình dạng của host XHR nội bộ VietnamWorks mà dự án đã từ chối gọi. 444 test pass; **verify live qua API + Postgres**: bật 2 nguồn qua trang Settings (patch chỉ nêu 2 key vẫn giữ đủ 9 source — merge-by-key của Phase 11 làm việc thật), crawl → 7 job vào DB, `posted_at` đủ 7/7, JD 2.6–7.8k chars, `apply_channel=external` 7/7, và Lever `duplicates=4` là các bản đăng lại nhiều thành phố bị gộp đúng theo `(company, normalized_title)`.

  **3 điều chỉ thấy khi đọc output thật:**
  1. **Greenhouse double-encode `content`** — JD về dạng `&lt;div&gt;…`. Lưu thẳng thì người đọc thấy tag thô còn agent tailor nhận markup như văn xuôi. Unescape đúng **một** lần: `&amp;` còn lại là cách mã hoá đúng của ký tự `&` *bên trong* HTML đã khôi phục.
  2. **Lever `createdAt` là mili-giây** (13 chữ số) và **payload không bao giờ ghi tên công ty**. Đổi ms→giây ngay tại scraper thay vì nới guard epoch (guard nhận 9–11 chữ số chính là để một con số 13 chữ số bất kỳ *không* bị hiểu thành ngày); tên công ty lấy từ slug trong `hostedUrl`. Ngoài ra JD của Lever nằm rải ở `description` + `lists` + `additional` — chỉ lấy `description` là đưa cho tailor bài PR của công ty mà không có yêu cầu nào để CV đáp (cùng bài học JSON-LD của VNW).
  3. **Any-word matching quá rộng trên board lớn**: query "backend engineer java" khớp 44/184 job GitLab, và 6 cái `limit` giữ lại là "AI Engineer" + 4 "Customer Success Engineer" — tất cả nhờ mỗi chữ *engineer*. Lọc chặt hơn sẽ vứt nhầm job tốt, nên **xếp hạng** thay vì lọc: `BaseScraper.rank_hits` (mặc định giữ nguyên — nguồn có search đã tự xếp hạng) và `FeedScraper` sắp theo số từ khoá khớp giảm dần. Sau khi sửa, 6/6 đều là Backend Engineer thật.

- ✅ **Phase 13** — ATS đọc được PDF không: `cv/ats.py` — build trả lời *"compile được chưa"*, file này trả lời *"máy đọc được không"*, và cái thứ hai mới quyết định có ai đọc CV hay không. Trích text layer rồi đối chiếu **những gì CV nói** với **những gì parser lấy lại được**: tên, email, điện thoại (so theo chữ số vì extraction làm xô lệch dấu cách), heading section, ligature (`ﬁ` phá keyword search), và độ phủ keyword của job. **Không có điểm số** — "ATS score 72/100" chẳng cho biết phải sửa gì, còn "email của bạn không nằm trong text layer" thì có. Keyword thiếu **không bao giờ chặn Approve**: chặn ở đó là mời người dùng dán skill không có vào CV, đúng thứ guardrail tailor sinh ra để ngăn. Surface ở `POST /cv/{scope}/compile` (`ats`) + panel ở CV Studio. 464 test pass; verify live bằng build Docker thật + kiểm chứng ngược (đổi email/tên trong doc → 2 error, message nêu đúng địa chỉ mà ATS sẽ gửi tới thay thế).

  **Bug đáng giá nhất của phase này là bug của chính checker.** Lần chạy thật đầu tiên, `pypdf` đọc một PDF Awesome-CV **hoàn toàn tốt** thành `FRESHERSOFTWAREENGINEER` và `WorkExperience` — mất sạch dấu cách — nên checker kết luận CV hỏng, thiếu heading. Đọc lại đúng file đó bằng **pdfminer.six**: "FRESHER SOFTWARE ENGINEER", "Work Experience", "Honors & Awards" — chuẩn từng khoảng trắng. **PDF chưa bao giờ hỏng; công cụ đo mới hỏng.** Báo hạn chế của công cụ thành lỗi của tài liệu còn tệ hơn không kiểm tra: nó đẩy người ta đi sửa một template vốn đã đúng. Nên: ưu tiên `pdfminer.six` (đã thêm vào extra `[cv]`), `pypdf` chỉ là fallback và **tự khai báo `spacing_reliable=False`** — khi đó mọi phép so khớp bỏ hết khoảng trắng ở cả hai vế, để một engine yếu không thể bịa ra finding. Cùng họ với bài học "`pages=0` vs `pages=None`": *không biết* và *hỏng* là hai khẳng định khác nhau.

- ✅ **Phase 14** — Vì sao điểm đó, và tin đó còn sống không: `crawler/quality.py` (thuần, **không LLM**). (1) `stack_coverage` gọi tên hai vế của `match_score` — job 0.25 và job 0.75 trước đây là bản án không kèm lý do, trong khi lý do vốn đã nằm sẵn trong danh sách `stacks` bạn tự khai. Dùng **đúng luật** của `stack_match_score`, không phát minh luật hay hơn: nếu lời giải thích bất đồng với con số nó giải thích thì nó thành một điểm số thứ hai đang cạnh tranh. (2) `flags_for` đánh dấu tin đáng xem lại: `no_jd`, `thin_jd` (<400 ký tự), `stale` (> `crawl.stale_days`, mặc định 45), `undated`. **Không cờ nào lọc bỏ job** — chỉ chú thích rồi để người quyết, giống cách crawler phơi gap ra chứ không tự lấp. `undated` tách khỏi `stale` vì *không biết tuổi* khác *già* (cùng họ `pages=None` vs `pages=0`). Web: tooltip trên MatchMeter liệt kê stack khớp/không khớp + badge cảnh báo ở trang Jobs và Job detail. 479 test pass; verify live trên Postgres thật: 7 job vừa crawl có đủ giải thích, và `cli backfill` gắn tín hiệu cho **66 row cũ** (chạy lần 2 → 0, idempotent) cho ra histogram thật **42 `no_jd` (toàn bộ LinkedIn alert), 10 `undated` (ITviec), 4 `stale` (Palantir reqs 2024–2025)** — tức 42/73 job trong DB không thể tailor nếu chưa dán JD, giờ nhìn phát biết thay vì tới lúc tailor mới lộ.

  **2 bẫy khi verify:**
  1. **`pkill` không giết được uvicorn trên Windows** → server cũ vẫn giữ cổng 8000, `curl` nói chuyện với **code cũ**, và crawl "thành công" mà không ghi quality nào. Suýt kết luận sai là tính năng hỏng. Giết theo cổng (`netstat -ano` → `taskkill //F //PID`) và kiểm `Application startup complete` trong log trước khi tin kết quả.
  2. **FastAPI serialize thẳng ORM row qua `from_attributes`**, nên override `model_validate` trên schema là **code chết** — không bao giờ được gọi. Chỗ đúng để lộ field dẫn xuất là `@property` trên chính model (`Job.quality`): một nơi duy nhất, cả route list lẫn detail đều nhận được.

### Nợ kỹ thuật còn lại (roadmap PLAN.md §9 đã xong)

- **Crawler**: ITviec + TopCV + VietnamWorks + LinkedIn(alerts) + WeWorkRemotely + Arbeitnow chạy thật; chỉ TopDev còn chưa có scraper (disabled trong config). Trang Runs chỉ cho chọn nguồn `enabled && ready` — `ready` = có scraper đăng ký trong `registry.SCRAPERS`, vì bật trong Settings không có nghĩa là đã implement. Cần `pip install -e '.[crawler]' && playwright install chromium` để crawl (2 nguồn tier-2 **không cần** Playwright).
- **Bật nguồn trên máy đã dùng Settings**: từ Phase 11, `config.local.yaml` merge **theo key** nên nguồn mới trong `config.yaml` luôn hiện ra; nhưng nếu overlay từng ghi `enabled: false` cho một key thì key đó vẫn tắt. Bật lại trong Settings, hoặc xoá `config.local.yaml`.
- **VietnamWorks lazy-load — đã xử lý bằng phân trang** (không phải scroll): 1 fetch vẫn chỉ render ~9–20 card, nhưng `search()` đi tiếp `?page=N` nên `jobs_per_site` > 9 vẫn đủ hàng (verify thật: 9 → **29 job**; trang 3 lặp lại trang 2 và bị guard bắt). Giữ nguyên `PlaywrightFetcher` là `(url) -> html` thuần — scroll sẽ đổi contract dùng chung cho mọi site, phân trang thì không.
- **TopCV thực tế chỉ lấy được ~50 job/lần crawl**: request thứ 2 trong cùng session bị Cloudflare chặn (403). Không phải bug — mặc định `jobs_per_site: 10` không bao giờ chạm tới, và khi chạm thì báo rõ "blocked — anti-bot" rồi giữ lại 50 hit của trang 1.
- **Query quá dài làm TopCV trả 0 kết quả**: keyword vào *path* nên "Java Spring Boot Backend" thành slug 4 từ → 0 job (crawl cảnh báo "try a shorter query"). `default_query` = 3 stack đầu, nên đổi thứ tự `crawl.stacks` là đổi luôn chất lượng search TopCV.
- **Nguồn tier-2 là remote/toàn cầu** (WWR: US/worldwide; Arbeitnow: Đức/EU, JD nhiều bài tiếng Đức) và **thiên về senior**, nên `exclude_keywords: [Senior, Lead, ...]` mặc định lọc đi khá nhiều. Tắt trong Settings nếu chỉ muốn job Việt Nam.
- **TopDev**: `robots.txt` `Allow: /` cho `User-agent: *` nhưng chặn riêng `ClaudeBot` và đặt `Content-Signal: ai-train=no, use=reference`. Chưa làm — không phải vì thiếu code mà vì cần quyết định rõ, và TopCV/VNW đã là 2 nguồn core đã chốt.
- **Bài học selector (ITviec)**: ITviec dùng utility CSS nên **match class theo substring là bẫy** — `[class*=city]` khớp `opa-city-50` khiến mọi job có location `"Hiring"`, `[class*=salary]` bắt trúng banner "IT Salary Report". Location/posted/salary giờ nhận diện **theo giá trị** (danh sách thành phố, regex thời gian), không theo cấu trúc. ITviec giấu lương sau login → `salary=None` là câu trả lời đúng, không phải placeholder. Test `test_itviec.py` ghim đúng các bẫy này. Bộ nhận diện theo giá trị nay dùng chung ở `crawler/vietnam.py` cho cả 3 site VN.
- **SQLite KHÔNG enforce `VARCHAR(n)`, Postgres thì có.** Verify crawl trên SQLite là chưa đủ: một field quá dài chỉ nổ khi chạy Postgres thật, và nó nổ *giữa flush* → `PendingRollbackError` **rollback cả crawl**, 1 field xấu làm mất sạch cả batch. `normalize._fit()` giờ clamp `title/company/location/salary` theo đúng width cột (payload vẫn giữ text đầy đủ). Verify crawl phải chạy qua **Postgres + API thật**, không chỉ SQLite.
- **Đừng quét salary trên cả body detail.** `.box-job-information-detail` của TopCV chứa cả panel "việc làm tương tự", và card trong đó **có lương riêng** sau khi hydrate → 2 job không liên quan cùng ra "20 - 60 triệu". Salary chỉ lấy từ nguồn chắc chắn thuộc job này: card của chính nó, hoặc `baseSalary`. Không có thì `None` là câu trả lời đúng. Cùng bài học với ITviec. `parse_salary` cũng có guard `MAX_SALARY_LEN=80` — lương là *label*, không phải đoạn văn (từng trả về nguyên blob 6.7 KB JD làm salary).
- **`select_one("a, b")` KHÔNG theo thứ tự selector** mà theo thứ tự trong document. Trên card VietnamWorks link logo đứng trước `h2 a`, nên one-liner lấy trúng logo (không có text, chỉ có `title`) và title lặng lẽ đến từ sai element. Dùng helper `_first(root, *selectors)` khi thứ tự ưu tiên là có ý.
- **Fetch strategy**: `PlaywrightFetcher` load bằng `domcontentloaded` rồi *cố* chờ `networkidle` trong 6s và bỏ qua nếu timeout. Chờ `networkidle` như điều kiện load là bẫy: job board chạy analytics/socket không bao giờ im, trang render xong nhưng `goto` treo tới timeout rồi fail cả crawl (đúng lỗi ITviec gặp). Từ Phase 11 nó **raise theo status code** — trang chặn (403/429) là một *trang* hợp lệ với parser, nên nếu không chặn ở tầng fetch thì nó lặng lẽ thành "0 job".
- **Chọn fetcher theo thứ site phục vụ, không theo thói quen**: `HttpFetcher` cho document (RSS/JSON/HTML server-render), `PlaywrightFetcher` cho app (ITviec/VNW). Đừng truyền 1 fetcher dùng chung cho mọi scraper trong production — `build_scrapers(fetcher=...)` chỉ dành cho test, vì browser sẽ bọc JSON thành `<pre>` và feed parser vỡ.
- **`infer_level` vẫn quét cả JD**, nên một JD nhắc "we hire senior engineers" có thể kéo job mid thành senior. Đã sửa phần substring (Phase 11) nhưng phạm vi quét thì chưa thu hẹp — thu về title-only sẽ mất các job VN ghi "thực tập sinh" trong body.
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
