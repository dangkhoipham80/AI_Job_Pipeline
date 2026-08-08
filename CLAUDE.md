# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này.

## Repo là gì

Hai lớp:
1. **CV Template** — bộ khung LaTeX [Awesome-CV](https://github.com/posquit0/Awesome-CV) (`awesome-cv.cls`, `fontawesome.sty`, `fonts/`), build bằng Docker. Repo **chỉ chứa khung**, không chứa CV nào.
2. **JobPilot (đang xây)** — agent crawl job (ITviec/TopCV/VietnamWorks) → quản lý qua **Web Dashboard local** (control plane chính; Slack là kênh phụ) → tailor CV → duyệt/sửa → apply hybrid. Stack: FastAPI + React + PostgreSQL. Xem `PLAN.md` (kiến trúc) và `SKILL.md` (logic tailor).

## Đọc trước khi làm

- `PLAN.md` — kiến trúc, data model, roadmap, quyết định đã chốt.
- `SKILL.md` — quy tắc tailor CV, **guardrail chống bịa**.
- `PHASES.md` — nhật ký từng phase (quyết định + bug chỉ lộ ra khi chạy thật). Đọc
  phần của vùng code mình sắp đụng, không cần đọc hết.
- File này — commands + conventions + nợ kỹ thuật đang còn.

## Nguyên tắc bắt buộc (đọc kỹ)

1. **Truthfulness**: khi tailor CV, KHÔNG bịa skill/kinh nghiệm/metric. Chỉ nhấn mạnh/diễn đạt lại dữ kiện có thật. Chi tiết: `SKILL.md §0`.
2. **Human-in-the-loop**: mọi hành động gửi ra ngoài cần user Approve, trừ kênh **email** đã bật rõ. **Không** auto-apply LinkedIn. **Không** scrape LinkedIn.
3. **Không commit thông tin cá nhân**: Master CV (tên, email, SĐT, học vấn, kinh nghiệm…) sống trong bảng `cv_versions` của Postgres và đi ra/vào qua API (`GET/PUT /cv/{scope}`). Repo không chứa CV nào — DB mới thì `ensure_master()` tạo **CV rỗng** (`cv/skeleton.py`), user tự điền trong CV Studio hoặc `jobpilot cv import <file.json>`. `cv/sample.py` là CV **hư cấu** chỉ dùng cho test + demo, app không bao giờ seed từ đó.
4. **Không ghi đè Master CV**: bản tailored sinh ra ở `out/cv/<scope>/`, Master trong DB giữ nguyên.
5. **Tôn trọng ToS/robots.txt/rate-limit** khi crawl. Site nào fail thì log + chạy tiếp, không retry vô hạn.
6. **Secrets**: mọi token (Slack, Claude API, email) đặt trong `.env` (đã gitignore). Không log, không commit token, không commit `jobpilot.db`.

## Quy trình triển khai (phase-by-phase + Review gate)

Triển khai theo phase trong `PLAN.md §9`. **Mỗi phase là một vòng khép kín:**

1. **Implement** trọn vẹn 1 phase (theo scope PLAN.md), verify chạy được (không chỉ dựa test).
2. **Summary for review** — xuất một tóm tắt chuẩn, gồm:
   - *Scope*: phase nào, mục tiêu.
   - *Changes*: danh sách file thêm/sửa + vai trò.
   - *Key decisions*: quyết định kỹ thuật + lý do.
   - *How to verify*: lệnh chạy thử + kết quả kỳ vọng.
   - *Risks / follow-ups*: điểm cần lưu ý, nợ kỹ thuật.
3. **Review gate** — chạy subagent `phase-reviewer` (định nghĩa ở
   `.claude/agents/phase-reviewer.md`) trên diff, kèm summary ở bước 2 làm context.
   Nó review **độc lập** trên `git diff` thật, không chỉ đọc summary — và nó biết
   các bẫy đã trả giá của repo (đọc `PHASES.md` + checklist trong định nghĩa agent).
   - ✅ **APPROVE** → trình verdict cho user, sang bước 4.
   - ❌ **CHANGES REQUESTED** → sửa theo finding, quay lại bước 2 (không push).
   - Reviewer **không tự sửa code** và **không tự push** — nó chỉ ra verdict;
     quyền quyết định vẫn ở user.
4. **Push git** — commit (message theo Conventional Commits) + push. Chỉ push **sau khi review approve và user đồng ý**.
5. **Tiếp phase sau.**

Ràng buộc:
- **Không tự merge/nhảy phase** khi chưa có approve.
- Mỗi phase = 1 (hoặc vài) commit gọn, message rõ; kết thúc phase mới push.
- Branch làm việc: `feat/jobpilot` (giữ `main` sạch), trừ khi user yêu cầu khác.
- Sau mỗi phase: ghi chi tiết vào `PHASES.md`, thêm 1 dòng vào bảng "Trạng thái hiện
  tại" bên dưới, cập nhật "Nợ kỹ thuật" nếu có gì đổi. **Giữ `CLAUDE.md` dưới 40k ký
  tự** — chi tiết đi vào `PHASES.md`, ở đây chỉ để thứ còn đang áp dụng.

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
python -m jobpilot.cli backfill     # gắn quality signal + facet phân tích cho job cũ (idempotent)
python -m jobpilot.cli backfill --force   # tính lại cả row đã có — dùng sau khi SỬA parser
python -m jobpilot.cli cv seed      # tạo Master CV rỗng nếu chưa có (idempotent)
python -m jobpilot.cli cv import my-cv.local.json   # nạp CV có sẵn vào DB
python -m jobpilot.cli cv export my-cv.local.json   # backup CV từ DB ra file (gitignored)
python -m jobpilot.cli cv build     # render JSON → .tex → PDF ở out/cv/master/
python -m jobpilot.cli tailor <job_id>            # tailor CV cho 1 job (cần key của provider đang chọn)
python -m jobpilot.cli tailor <job_id> --no-build # chỉ ra plan, không build PDF
python -m jobpilot.cli apply <job_id>             # nộp theo kênh (email/portal/external)
python -m jobpilot.cli apply <job_id> --open-portal   # portal: mở browser pre-fill (không tự submit)
python -m jobpilot.cli confirm-submit <job_id>    # xác nhận đã tự nộp xong (portal/external)
python -m jobpilot.cli llm providers # provider nào đang chạy việc gì, có key chưa, terms ra sao
python -m jobpilot.cli llm stats    # chi phí / tỉ lệ qua guardrail lần đầu / độ trễ, theo backend
python -m jobpilot.cli llm bench --task classify  # chấm trên 5 email có đáp án (mốc qwen2.5:7b = 5/5)
python -m jobpilot.cli llm bench --task tailor    # chạy 4 job thật, đếm plan qua guardrail (mốc = 0/4)
python -m jobpilot.cli slack        # (tùy chọn) Slack Bolt — kênh phụ; cần API đang chạy
pytest jobpilot/tests               # test
# tất cả trong 1 lệnh:
make dev
```

## Conventions

- **Ngôn ngữ code/comment**: English. Docs cho user (PLAN/SKILL/PHASES) có thể tiếng Việt.
  **Mọi thứ đẩy lên GitHub thì English**: commit message, PR title, PR description, issue.
  Ranh giới là *ai đọc*: `PHASES.md` là nhật ký cho mình, PR là thứ public.
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

> Có subagent `scraper-smith` (`.claude/agents/scraper-smith.md`) đóng gói đúng quy
> trình dưới đây + toàn bộ bẫy đã gặp. Dùng nó thay vì làm tay.

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

Roadmap `PLAN.md §9` **đã xong** (Phase 0 → 15), và roadmap mở rộng **`PLAN.md §9.1`
(Phase 18 → 25)** đang chạy — Phase 18–20b xong, tiếp theo là **analytics thật** (ô "20"
trong bảng §9.1; hai phase model backend dùng nhờ số 20 nên analytics vẫn còn nợ).
Nhật ký chi tiết từng phase — scope,
quyết định kỹ thuật, và các bug chỉ lộ ra khi chạy thật — nằm ở **`PHASES.md`**. Đọc
phần tương ứng trong đó trước khi đụng vào một vùng code lần đầu; mục "Nợ kỹ thuật"
ngay bên dưới là phần **còn đang áp dụng**, đủ cho việc thường ngày.

| Phase | Nội dung | Code |
|---|---|---|
| 0–2 | scaffold; build wrapper Docker LaTeX; models + Alembic + FastAPI skeleton | `store/`, `api/`, `alembic/` |
| 3 | crawler framework (pure `search_url`/`parse_*`, robots, rate-limit, dedup) + ITviec | `crawler/base.py`, `pipeline.py`, `persist.py` |
| 4 | Web Dashboard: jobs/funnel/charts + realtime WS | `web/`, `api/main.py` |
| 4.5 | CV Studio: JSON `CvDocument` → Jinja2 `.tex` → Docker PDF, `cv_versions` append-only | `cv/` |
| 5 | Tailor engine **index-based** + guardrail chống bịa (structural + lexical) + CV Review | `tailor/` |
| 6 | Apply dispatcher (email 3 gate / portal / external) + Applications board | `apply/` |
| 7 | Slack — **client thuần của REST API**, backend không biết gì về Slack | `slack/` |
| 8 | `TaskQueue` 1 worker + trang Runs/Settings (`config.local.yaml` overlay) | `orchestrator.py`, `config.py` |
| 9 | TopCV + VietnamWorks chạy thật; JSON-LD `JobPosting` + nhận diện theo giá trị dùng chung | `crawler/jsonld.py`, `vietnam.py` |
| 10 | Tailor/apply rời request path → **202 + task**; guard 1 task/1 job nằm trong `submit()` | `orchestrator.py`, `tailor/service.py` |
| 11 | Phân trang nhiều trang + `FeedScraper` (RSS/JSON) + WeWorkRemotely/Arbeitnow | `crawler/base.py`, `feed.py` |
| 12 | ATS adapter tier-3 — 1 adapter phủ mọi công ty dùng Greenhouse/Lever | `crawler/ats.py` |
| 13 | Máy đọc được PDF không (text layer, **không chấm điểm**) | `cv/ats.py` |
| 14 | Giải thích `match_score` + cờ chất lượng tin (`no_jd`/`thin_jd`/`stale`/`undated`) | `crawler/quality.py` |
| 15 | Nhắc follow-up sau khi nộp — hiện trên board, **không tự gửi** | `apply/followup.py` |
| 16 | Diff giữa 2 version CV bất kỳ trong CV Studio (dùng lại diff của tailor) | `tailor/diff.py`, `api/routes/cv.py` |
| 17 | Cover letter ra `.tex` → PDF, đính kèm email; text vẫn là bản chính | `apply/letter_pdf.py`, migration 0006 |
| 18 | Chuyện gì xảy ra **sau** khi nộp: replied/interview/offer/rejected + lịch sử | `apply/outcome.py`, migration 0007 |
| 19 | Đọc thư NTD → **đề xuất** outcome, user bấm mới ghi | `apply/inbox.py`, migration 0008 |
| 20 | Chạy model **trên máy mình** (Ollama) — chọn provider theo từng việc | ~~`llm/ollama.py`~~ (gỡ ở 20b) |
| 20b | Một tầng provider: claude/openai/gemini, cảnh báo dữ liệu, **đo chi phí + chất lượng** | `llm/`, migration 0009, `llm/stats.py` |
| 21 | Trang **/market**: nghiên cứu thị trường từ corpus đã crawl + trích lương/skill/city | `analytics/`, `crawler/salary.py`, `skills.py` |
| 20c | Trang **/models**: chọn model theo việc, dashboard giá + credit đã dùng/còn, scrub key | `web/src/pages/Models.tsx`, `llm/redact.py` |

637 test pass. Đã verify trên môi trường thật: Alembic lên **PostgreSQL 17 local**
(0009 up→down→up sạch), 8 trang web, Docker LaTeX build (Master + tailored), crawl 6+ nguồn
qua API + Postgres, `llm_calls` ghi/đọc qua Postgres thật + `GET /stats/llm` + `llm bench`.
**Đã gọi thật cả ba provider thành công** (Claude, Gemini; OpenAI qua key trong `.env`) —
classify 5/5 trên 6 model, tailor **2/2 qua guardrail vòng đầu** trên job thật. Trang `/models`
đã chụp thật ở cả light/dark, console sạch, đổi model từ UI ghi xuống `config.local.yaml` và
lệnh CLI chạy đúng backend mới.
**Cả ba provider đã chạy thật cho cả schema phẳng (`MailVerdict`) lẫn schema lồng (`TailorPlan`)**,
kể cả OpenAI strict mode. Biến môi trường `OPENAI_API_KEY` cũ đã gỡ; `llm providers` và trang
`/models` không còn cảnh báo shadow.

**Bài học xuyên suốt** (ca cụ thể ở `PHASES.md`):
- **Test xanh không chứng minh parser đúng.** Mỗi phase crawl đều có bug chỉ lộ ra khi
  chạy thật. Verify qua **Postgres + API thật** rồi *đọc output*, không dừng ở test.
- **Sai dữ liệu *trông như đúng* tệ hơn thiếu dữ liệu.** Param bị site lặng lẽ bỏ qua,
  trang 403 parse thành "hết kết quả", `"remote" in "remote debugging"`, `intern` nằm
  trong `internal`. Cái nguy hiểm luôn là thứ báo cáo thành công.
- ***Không biết* ≠ *hỏng*.** `pages=None` vs `pages=0`, `undated` vs `stale`,
  `spacing_reliable=False` thay vì kết luận PDF lỗi.
- **Đừng để công cụ đo bịa ra finding.** `pypdf` đọc mất dấu cách rồi kết luận CV hỏng —
  PDF chưa bao giờ hỏng, công cụ đo mới hỏng.

### Model backend (Phase 20 → 20b) — đọc trước khi đổi provider

- **Chọn theo từng việc, không phải một công tắc.** `llm.tailor` / `llm.letter` / `llm.classify`
  (rỗng = rơi về `llm.provider`, mặc định `claude`). Provider hợp lệ nằm ở
  `llm/registry.PROVIDERS` — thêm một backend = **một entry + một module client**, không sửa
  `Literal` ở bốn chỗ. Model chọn theo `llm.models[provider]`, ghi đè theo việc bằng
  `llm.task_models[task]`.
- **Một engine cho mỗi task, không phải một engine cho mỗi provider.** `ModelTailorEngine` /
  `ModelLetterEngine` / `ModelClassifier`, mỗi cái cầm một `StructuredClient`. Vòng retry là thứ
  chặn một plan sai lọt vào PDF, nên nó **không được** có bản sao theo backend — trước 20b thì
  `letter.py` đã có đúng hai bản gần giống nhau. Giờ bất biến đó do *không còn gì để fork* giữ,
  không phải do một test giữ.
- **Ba provider không nhận cùng một JSON Schema.** `llm/schema.py`: `flatten_schema` (Gemini —
  docs chỉ liệt kê subset, cảnh báo schema lồng sâu có thể bị từ chối), `strictify` (OpenAI
  strict — mọi object `additionalProperties:false`, **mọi** field trong `required`). Bẫy ở
  `strictify`: "mọi field required" **không** có nghĩa bỏ field optional — optional được nới
  thành nullable, nếu không model bị ép **bịa** ra `summary`.
- **Đo, đừng đoán.** Mọi lượt gọi ghi một row `llm_calls` (**kể cả lượt bị guard từ chối, kể cả
  lượt gọi hỏng**). Đọc bằng `GET /stats/llm` hoặc `jobpilot llm stats`. `jobpilot llm bench
  --task classify|tailor` chạy lại đúng phép đo của Phase 20 (5 email có đáp án / 4 job thật).
  Mốc `qwen2.5:7b` để so: classify **5/5**, tailor **0/4**.
- **Mẫu nhỏ thì hiện `n=<count>`, không hiện %.** `llm/stats.MIN_SAMPLE`. 3 lượt 2 lỗi không
  phải "33%", nó là 3 lượt — và tỉ lệ thì mời người ta so sánh hai backend trên 3 lượt.
- **`cost_usd = NULL` khác `0.00`.** Model không có trong `llm/pricing.PRICES` thì không đoán
  giá; `unpriced_rounds` đi kèm mọi tổng, để một tổng dựng từ nửa số row không bị đọc như dựng
  từ tất cả. Bảng giá có `CHECKED_ON` — nó **sẽ** cũ đi.
- **Chỉ một ô cần cảnh báo: Gemini free tier.** Anthropic / OpenAI / Gemini **trả tiền** đều
  không train trên input API. Gemini **unpaid** thì có, và điều khoản ghi thẳng *"Do not submit
  sensitive, confidential, or personal information"* — trong khi `tailor`/`letter` gửi **cả
  Master CV** (`prompt.py:system_prompt`). Không đọc được tier từ API key, nên có
  `llm.gemini_paid_tier`. `llm.warnings()` **cảnh báo, không chặn** — quyền là của user.
- **`llm.blocker(task)` kiểm tra key, không kiểm tra credit.** Key hỏng hay hết tiền chỉ biết
  bằng cách tiêu một request; giả vờ ngược lại chỉ là cách sai chậm hơn. Nó nằm trong
  `get_engine()` của route (không nằm trong route body) để test tự cấp engine không bị đòi key —
  đúng cái bẫy `test_missing_tokens_produce_a_readable_error` đã dính.
- **Telemetry không bao giờ được làm hỏng việc nó đo.** `usage.record` ghi hai lần: có link
  job/application, rồi nếu vỡ thì không link. Bản đầu nuốt lỗi im lặng và **mất sạch** row của
  `llm bench` vì FK — chỉ lộ ra khi chạy thật, đúng thứ mà "nuốt lỗi" che đi.
- **Prompt phải nói ra thứ schema đã ngầm định.** `section_order` để rỗng = giữ nguyên; outline
  in `type=` nhưng phải giải thích kiểu nào dùng field nào. `retry_prompt` phải nhắc lại **đúng
  luật vừa vỡ** (`_REMEDIES`) — bản cũ khuyên về index/summary trong khi cái vỡ là `section_order`.
- **Ba luật chốt cho model backend (user đặt, không tự đổi):** (1) **không được leak API key** —
  đây là rủi ro, không phải chi tiết; (2) **model phải đổi được từ Web** (trang `/models`: chọn
  provider+model cho từng việc, dashboard giá/chất lượng/độ trễ, credit đã dùng/còn lại);
  (3) **mặc định dùng model rẻ nhất mà vẫn hiệu quả**, chứng minh bằng `llm bench` chứ không đoán.
- **Scrub key ở chỗ *tạo ra* lỗi, không phải ở từng nơi lỗi đi tới.** `llm/redact.py` gọi từ
  `LlmError.__init__` + `CallLog`. Lý do rất cụ thể: key sai thì provider **trích lại key** trong
  message (`Incorrect API key provided: sk-proj-…`), và chuỗi đó đi thẳng vào `llm_calls.error`,
  ra CLI, ra API. Thêm `log.warning` nào mang exception của SDK thì cũng phải `redact()`.
  Có test ghim: field nào **tên** giống secret **và** kiểu string thì không được xuất hiện trong API.
- **"Credit còn lại" KHÔNG lấy được từ provider.** Anthropic/OpenAI/Google đều đòi **Admin key**
  cho endpoint chi phí (đã thử, cả ba trả 401). Nên nó là `llm.budget_usd` (tự nhập) trừ đi phần
  **JobPilot tự đo** — là bộ đếm ngân sách, không phải số dư tài khoản, và UI phải nói đúng thế.
- **Mặc định hiện tại: `classify` = `openai/gpt-4o-mini`** (10 lượt, 100% đúng, rẻ nhất **và**
  nhanh nhất). `tailor`/`letter` giữ `claude-opus-4-8`.
- **Bài học về chính bộ đo này: n=5 đã cho kết luận SAI.** Ở 5 lượt `gemini-3.1-flash-lite` trông
  nhanh nhất (p50 **705ms**); lên 10 lượt p50 thành **2732ms**, còn `gpt-4o-mini` 1101ms — đảo
  ngược cả "rẻ nhất" lẫn "nhanh nhất". Đúng là lý do `MIN_SAMPLE` tồn tại, và nó vừa bắt được
  chính người viết ra nó. **Đừng chốt model khi cột tỉ lệ còn hiện `n=<count>`.**
- **Mọi model đã thử đều 5/5 trên bộ classify** ⇒ với việc này phân biệt bằng **giá + độ trễ**,
  không phải độ chính xác: `gpt-4o-mini`, `gpt-4.1-mini`, `gemini-3.1-flash-lite`,
  `gemini-3.5-flash-lite`, `claude-haiku-4-5`, `gpt-4.1`, `gemini-3.5-flash` (đắt nhất — thinking
  token tính giá output).
- **`tailor` đã chạy thật trên hai backend**: `claude-opus-4-8` **2/2** qua guardrail vòng đầu
  (~$0.10/lượt, ~39s); `gpt-4.1` **1/1** vòng đầu (~$0.016/lượt, ~9s) — rẻ hơn ~6×, nhanh hơn ~4×.
  **Chưa đổi**: guardrail chỉ bắt *bịa*, không bắt "đúng sự thật nhưng xếp hạng dở", nên tailor
  phải chấm bằng mắt ở trang CV Review; n=1 chưa phải bằng chứng.
- **`thinking` không bật cho mọi model được.** Haiku trả 400 *"adaptive thinking is not supported
  on this model"* ⇒ để nguyên là **chặn luôn cả tầng model rẻ**. Giờ registry tắt thinking cho
  `classify`, và client tự tắt + gọi lại một lần khi gặp đúng lỗi đó (không hardcode danh sách model).
- **Provider *liệt kê* model không có nghĩa là dùng được.** `gemini-2.5-flash` nằm trong
  `models.list()` nhưng `generateContent` trả **404 "no longer available to new users"**. Danh sách
  chỉ là *menu*, `llm bench` mới là bằng chứng. Và khi so id thì phải **so theo prefix**:
  Anthropic liệt kê `claude-haiku-4-5-20251001` còn alias mình gọi là `claude-haiku-4-5` — so khớp
  chính xác từng đánh dấu nhầm model đang chạy tốt là "không khả dụng".
- **Ollama đã gỡ (20b).** Đánh đổi có ý thức: `classify` từng chạy local 5/5 và thư nhà tuyển
  dụng **không rời khỏi máy**; giờ nó đi qua API. Cái *vẫn* đúng: thư không khớp đơn nào vẫn
  dừng trong máy. Muốn quay lại local thì Ollama có endpoint OpenAI-compatible
  (`localhost:11434/v1`) map `response_format` vào cùng grammar — tức **một entry trong
  `PROVIDERS` với `base_url` khác**, không phải viết lại module.

### Market analytics (Phase 21) — đọc trước khi thêm biểu đồ

- **Mỗi aggregate phải trả kèm `covered`/`total`.** `analytics/market.Facet`. Corpus này 57% là
  LinkedIn, mà LinkedIn **không có** skill/lương/tag ⇒ biểu đồ không kèm mẫu số thì đang mô tả
  *mấy board chịu gắn tag* nhưng trông như mô tả *thị trường*. UI in "18 of 73 jobs", **không**
  in % trần trụi. Dưới `MIN_SAMPLE=8` thì có `note` cảnh báo.
- **Trang `/market` mô tả *corpus đã crawl*, không phải thị trường VN.** Câu này nằm ngay đầu
  trang, cố ý.
- **Facet là dữ liệu dẫn xuất, luôn nằm CẠNH giá trị thô** (`skills` vs `skills_canonical`,
  `salary` vs `salary_range`). Parser sai thì còn thứ để chạy lại — `backfill --force`.
- **Ba nguồn nhiễu đã trả giá, cả ba cùng một dạng "trông như đúng":**
  1. Tag của board xếp `+2` (badge tràn của card ITviec), `Vollzeit`, `Backend Developer`,
     `IT Services and IT Consulting`, `India` ngang hàng với `Java`. Lọc bằng **pattern**
     (`_ROLE_RE` khớp danh từ số ít ⇒ bỏ "software engineer", giữ "data engineering"), không
     bằng blocklist dài mãi.
  2. `Hà Nội` / `Ha Noi` / `Hanoi` thành **ba** cột, mỗi cột 1/3 số thật. `vietnam.canonical_city`
     fold ASCII (cùng cách `apply/inbox.fold` làm) rồi map alias.
  3. `"15tr - 25tr"` parse ra **15–15**: unit nằm giữa số và dấu gạch làm vỡ regex range, rơi
     xuống nhánh một-số. Trần bị giảm một nửa mà không báo gì.
- **Lương: không đoán.** Không có ký hiệu tiền tệ ⇒ `None` ("20 - 60" là triệu VND hay USD/giờ
  tuỳ board). "Up to 3000" ⇒ `min=None`, **không** bịa 0. Quy đổi sang USD/tháng dùng
  `salary.USD_VND_RATE` có `FX_CHECKED_ON` — là **ước tính**, UI phải nói thế.
- **Màu: một measure thì một màu.** Tô 8 màu xuống 15 dòng là tô theo *thứ hạng* — đổi filter là
  đổi màu. Chỉ facet mà mỗi dòng là một *thực thể* (source) mới truyền hàm màu. Và
  `SOURCE_ORDER` phải **đúng bằng số hue**: dài hơn thì wrap, `lever` đội màu của `itviec`.
- **`posting_calendar` dùng `posted_at`**, khác biểu đồ `by_day` của Deck (dùng `crawled_at` —
  đo thói quen chạy crawler của mình, không đo thị trường).

### Inbox sync (Phase 19) — đọc trước khi đụng vào `apply/inbox.py`

- **Thứ tự fetch → ghép cục bộ → LLM là thiết kế riêng tư, không phải tối ưu.** Thư không
  thuộc đơn nào **dừng lại ngay trong máy**; chỉ thư đã khớp mới tới model. Đừng đảo thứ
  tự, đừng "gửi hết cho model cho gọn" — có test ghim
  (`test_unmatched_mail_is_never_handed_to_the_classifier`). Từ Phase 20b, thư **đã khớp**
  luôn đi qua API của provider (không còn đường local), nên bước ghép cục bộ **là** phần bảo
  vệ, và nó phải đứng trước.
- **`quote` phải xuất hiện thật trong thư**, nếu không verdict bị loại và lưu status
  `unusable`. **Vẫn phải lưu** dù bị loại: không lưu thì lần sync sau thư đó lại "mới" và
  lại gọi Claude — trả tiền vô hạn cho một câu trả lời không bao giờ hiển thị.
- **Bật cần `apply.inbox.enabled`** + `IMAP_USER`/`IMAP_PASSWORD` (Gmail phải là App
  Password). Mặc định **tắt** — đọc hộp thư của người khác không phải thứ tự ý bật hộ.
  `apply.inbox.folder` cho ai muốn siết vào một label riêng.
- **Chỉ đề xuất `replied`/`interview`/`offer`/`rejected`.** `withdrawn`/`ghosted` là quyền
  tự khai của user. "Đã nhận hồ sơ" là `auto_ack`, không phải `replied`.
- **Tên công ty phải fold về ASCII trước khi so với domain** (`inbox.fold`) — domain không
  bao giờ có dấu, nên "Công ty TNHH X" mà không fold sẽ giữ `công` như phần đặc trưng.
- **`meta` là JSONB do bất kỳ phiên bản dispatcher nào ghi** — đọc field trong đó ở React
  phải optional-chain. Một row thiếu key từng làm trắng cả trang Applications.

### Outcome tracking (Phase 18) — đọc trước khi đụng vào số liệu

- **`/stats` trả hai bộ đếm và chúng không thay thế nhau được.** `/stats` trả **hai**
  bộ đếm và chúng **không** thay thế nhau được: `current` đếm theo `Application.outcome_stage`
  (board đang hiện gì), `reached` đếm `COUNT(DISTINCT application_id)` trên
  `application_events` chưa retract (đã từng tới chặng nào). **Mọi tỉ lệ phải dùng
  `reached`** — một đơn phỏng vấn 2 vòng rồi bị từ chối chỉ nằm ở `current["rejected"]`, nên
  tính interview rate theo `current` sẽ báo số đơn đang *kẹt* ở vòng phỏng vấn, một con số
  tụt xuống khi mọi việc đang tốt lên. Có test ghim ở cả `test_outcome.py` lẫn
  `test_outcome_api.py`; đừng "đơn giản hoá" về một bộ.
- **Outcome sống ở tầng `Application`, không đụng `JobStatus`.** Thêm value vào Postgres
  enum cần `ALTER TYPE … ADD VALUE` (không chạy trong transaction block) và kéo theo
  `web/src/lib/statuses.ts` + funnel + `slack/events.py`. Job `SUBMITTED` vẫn `SUBMITTED` dù
  sau đó offer hay bị từ chối. Muốn thêm loại outcome mới thì thêm một chuỗi vào
  `apply/outcome.ALL_OUTCOMES` + `OutcomeType` bên Pydantic/TS — **không** cần migration.
- **`ghosted` không tự suy ra theo bộ đếm ngày**, và outcome không bao giờ tự ghi. Phase 19
  (inbox sync) cũng chỉ được *đề xuất*: mail vào → gợi ý → user bấm xác nhận mới ghi.
- **Guard double-click trong React phải là `useRef`, không phải state.** Hai click cùng một
  tick đều đọc `busy === false` (chưa re-render giữa hai lần) nên state check để lọt click
  thứ hai và ghi event trùng. Xem `web/src/components/OutcomeTracker.tsx`.

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
- **CV Studio**: chưa có HTML live preview, theme gallery, raw LaTeX mode (Monaco). Diff giữa 2 version bất kỳ **đã có** (Phase 16) — dùng chung `tailor/diff.py` với CV Review, chỉ khác bộ chữ (`VERSION_LABELS` vs `TAILOR_LABELS`). Thêm loại so sánh mới thì thêm một `DiffLabels`, **đừng fork hàm diff**: hai bộ luật song song sẽ lệch nhau lúc nào không biết.
- **Cover letter đã ra PDF** (Phase 17): template riêng `cv/templates/awesome_cv/cover_letter.tex.j2` dùng chung `_preamble.tex.j2` với CV. **`awesome-cv.cls` bản trim trong repo KHÔNG có macro letter nào** (`\cvletter`, `\recipient`… đều không tồn tại — grep class file trước khi tin spec). Text vẫn là bản chính (email mang text ở body, PDF là đính kèm); build hỏng thì **đơn vẫn gửi**, lý do vào `meta.letter.pdf_error`. Ngắt đoạn trong template LaTeX phải viết `\par` tường minh — Jinja `trim_blocks` ăn dòng trống và biến 2 đoạn thành 1 dòng dính liền, compile vẫn sạch.
- **Cần `pip install -e '.[cv]'`** cho `pypdf`, nếu không page count trả `None` (badge "1 trang" biến mất, không còn cảnh báo CV tràn 2 trang). Build PDF vẫn chạy bình thường — chỉ mất phần đếm trang.
- **Queue vẫn 1 worker**: tailor xếp sau một crawl đang chạy sẽ đứng `queued` vài phút. Đúng nghĩa "queued", nhưng nếu thấy vướng thì nâng `max_workers` — task body đã mở session riêng nên an toàn về mặt DB.
- **Slack đã verify thật** (2026-08-08): app cần đúng **một** scope `chat:write`, cộng Socket Mode
  + app-level token `connections:write`, cộng bật **Interactivity** (quên cái này thì tin nhắn vẫn
  hiện mà bấm nút im lặng), cộng `/invite @jobpilot` vào channel. Bấm nút trên Slack đổi state
  trong Postgres và dashboard thấy ngay — `PLAN.md §10` đã được quan sát, không còn là giả định.
  Lỗi hay gặp: channel **riêng tư** mà bot chưa được mời trả `channel_not_found`, không phải
  `not_in_channel` — hai lỗi đó phân biệt public/private.
- **Chưa verify được: một lượt gọi model *thành công*.** Anthropic: key hợp lệ nhưng **hết
  credit** (400 `credit balance is too low`). OpenAI: `OPENAI_API_KEY` trong `.env` bị từ chối
  **401**. Gemini: chưa có `GOOGLE_API_KEY`. Nghĩa là **shape request của OpenAI/Gemini chưa
  đối chiếu với API thật** — 401 xảy ra *trước* khi request được validate. Đường lỗi thì đã
  chạy thật đầu-cuối (bench → `llm_calls` trong Postgres → `/stats/llm`). Có key rồi thì việc
  đầu tiên là `jobpilot llm bench --task classify`, và **rủi ro cao nhất là Gemini có nuốt nổi
  `TailorPlan` không** — docs chỉ hỗ trợ subset JSON Schema.
- **Đã verify trên môi trường thật**: `alembic upgrade head` chạy sạch 3 migration lên **PostgreSQL 17 local** (schema `jobpilot`, GIN index, enum `job_status` đầy đủ); toàn bộ 8 trang web chạy trên Postgres thật, không lỗi console; Compile PDF từ CV Studio và tailor→PDF đều qua Docker LaTeX thật.
- **Lưu ý khi chụp/screenshot UI**: headless Chrome **không có PDF viewer**, nên khung preview PDF sẽ trống (`net::ERR_ABORTED` trên blob URL). Đó là giới hạn của headless chứ không phải bug — chạy `headless=False` để kiểm tra thật.
- **Gmail OAuth** chưa làm — dùng `method: smtp` (Gmail app password chạy được).

## Quyết định đã chốt (không tự đổi nếu user không yêu cầu)

- Apply = **hybrid theo kênh** (email full-auto, portal/LinkedIn human-in-the-loop).
- Nguồn = **ITviec + TopCV + VietnamWorks** lõi (pluggable, mở rộng theo tier — PLAN.md §5.1.1); không LinkedIn/Facebook.
- Giao diện = **Web Dashboard local** là chính, **Slack** phụ. DB = **PostgreSQL**.
- Chạy = **local**, tay hoặc cron nhẹ.
- Stack = Python (FastAPI + Playwright stealth + Docker LaTeX) + React(Vite/TS/Tailwind/shadcn) + PostgreSQL + slack-bolt.
- LLM = **Claude mặc định**, openai/gemini chọn được **theo từng việc** (`llm.*`, Phase 20b). Không chạy model local.
