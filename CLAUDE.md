# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này.

## Repo là gì

Hai lớp:
1. **CV Template (đang có)** — CV LaTeX theo [Awesome-CV](https://github.com/posquit0/Awesome-CV), build bằng Docker. `cv.tex` là entry, nội dung tách trong `resume/*.tex`. Đây là **Master CV** (nguồn sự thật) của Khoi Pham — Fresher/Junior Backend (Java Spring Boot), FPT University, tốt nghiệp 04/2026.
2. **JobPilot (đang xây)** — agent crawl job (ITviec/TopCV/VietnamWorks) → quản lý qua **Web Dashboard local** (control plane chính; Slack là kênh phụ) → tailor CV → duyệt/sửa → apply hybrid. Stack: FastAPI + React + PostgreSQL. Xem `PLAN.md` (kiến trúc) và `SKILL.md` (logic tailor).

## Đọc trước khi làm

- `PLAN.md` — kiến trúc, data model, roadmap, quyết định đã chốt.
- `SKILL.md` — quy tắc tailor CV, **guardrail chống bịa**.
- File này — commands + conventions.

## Nguyên tắc bắt buộc (đọc kỹ)

1. **Truthfulness**: khi tailor CV, KHÔNG bịa skill/kinh nghiệm/metric. Chỉ nhấn mạnh/diễn đạt lại dữ kiện có thật. Chi tiết: `SKILL.md §0`.
2. **Human-in-the-loop**: mọi hành động gửi ra ngoài cần user Approve, trừ kênh **email** đã bật rõ. **Không** auto-apply LinkedIn. **Không** scrape LinkedIn.
3. **Không ghi đè Master CV**: bản tailored sinh ra ở `out/<job_id>/`. `resume/` giữ nguyên là Master.
4. **Tôn trọng ToS/robots.txt/rate-limit** khi crawl. Site nào fail thì log + chạy tiếp, không retry vô hạn.
5. **Secrets**: mọi token (Slack, Claude API, email) đặt trong `.env` (đã gitignore). Không log, không commit token, không commit `jobpilot.db`.

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
docker-compose up -d postgres       # dựng Postgres local
alembic upgrade head                # migrate DB
uvicorn jobpilot.api.main:app --reload   # API backend (REST + WebSocket) tại :8000
cd web && npm run dev               # Web Dashboard (Vite) tại :5173  ← control plane chính
python -m jobpilot.cli crawl        # crawl 3 site → Postgres (hoặc bấm Crawl trên dashboard)
python -m jobpilot.slack.app        # (tùy chọn) Slack Bolt — kênh phụ, thông báo/nút nhanh
pytest jobpilot/tests               # test
# tất cả trong 1 lệnh:
make dev
```

## Conventions

- **Ngôn ngữ code/comment**: English. Docs cho user (PLAN/SKILL) có thể tiếng Việt.
- **Python**: 3.11+, type hints, `ruff`/`black` nếu có. Mỗi scraper kế thừa `crawler/base.py:BaseScraper`.
- **LaTeX**: giữ cú pháp Awesome-CV; dùng macro có sẵn `\tech{}`, `\techfe{}`, `\cvsimpleentry`, `\cvitems`. Đổi màu chủ đạo tại `cv.tex` (`\colorlet{awesome}{...}`).
- **Job schema**: mọi scraper phải normalize về `Job` schema chung (PLAN.md §3.1) để dedup theo `id = "<source>:<native_id>"`.
- **State**: **Postgres là nguồn sự thật duy nhất**; mọi thay đổi trạng thái đi qua API backend (Web và Slack cùng gọi API → không lệch state). Orchestrator idempotent (chạy lại không hỏng). Đẩy update realtime qua WebSocket (web) + update message (Slack).
- **Web/Frontend**: React + Vite + TS + TailwindCSS + shadcn/ui; charts theo skill `dataviz`, UI theo skill `frontend-design` (palette nhất quán light/dark, có cá tính riêng). Bind `localhost`, không expose ra ngoài. DB migrations bằng Alembic — đổi schema phải tạo migration, không sửa tay.
- **CV data flow (quan trọng)**: nguồn sự thật của nội dung CV là **JSON structured** (CV Studio + agent tailor cùng dùng) → serialize ra `.tex` qua Jinja2 → Docker build PDF. Không sửa `.tex` tailored bằng tay ngoài luồng này (trừ raw-mode trong Studio, có cảnh báo mất round-trip). Mọi lần save = 1 row `cv_versions` (author = user|agent).
- **Verify thay đổi runtime**: sau khi sửa scraper/tailor/apply, chạy thử flow tương ứng và quan sát output thật, đừng chỉ dựa vào test. Sau khi sửa `resume/*.tex` phải build lại PDF để chắc không lỗi LaTeX.

## Thêm một site crawl mới

1. Tạo `crawler/<site>.py` kế thừa `BaseScraper`, cài `search()` + `parse_detail()`.
2. Normalize output về `Job` schema; set `apply_channel`/`apply_target`.
3. Thêm rate-limit + đọc robots.txt; test với snapshot HTML để tránh phụ thuộc mạng.
4. Đăng ký site trong `config.yaml`.

## Trạng thái hiện tại

- ✅ Master CV LaTeX hoạt động (`cv.tex` + `resume/*.tex`, build Docker).
- ✅ Docs nền tảng: `PLAN.md`, `SKILL.md`, `CLAUDE.md`.
- ✅ **Phase 0** — scaffold `jobpilot/` + `web/` (placeholder) + `docker-compose` + `pyproject` + `Makefile` + `config.yaml`/`.env.example` + config loader + CLI + smoke tests.
- ✅ **Phase 1** — Python build wrapper (`tailor/build.py` + `cli build`, Docker LaTeX, page-count qua pypdf) + cải thiện Skills của Master CV (ATS, giữ 1 trang) + untrack LaTeX aux cũ. *(chờ Codex review → push)*
- ✅ **Phase 2** — Data + API skeleton: SQLAlchemy 2.0 models (`store/models.py`: jobs/applications/edits/runs/cv_versions + `JobStatus` enum) + engine/session (`store/db.py`, sync psycopg3, schema `jobpilot`, SQLite translate-map cho test) + Alembic (initial migration, GIN trên payload) + FastAPI (`api/main.py`: `GET /jobs`, `GET /jobs/{id}`, `GET /stats`, `WS /ws`, token auth, CORS localhost) + `cli serve`. 25 test pass; verify live HTTP+WS trên SQLite; migration render Postgres DDL hợp lệ (Docker chưa chạy nên chưa `alembic upgrade` lên Postgres thật). *(chờ Codex review → push)*
- ✅ **Phase 3** — Crawler MVP: `crawler/` framework (`base.BaseScraper` template + pure `search_url`/`parse_search`/`parse_detail`; `fetch.PlaywrightFetcher` lazy import; `ratelimit` jittered delay; `robots` policy; `text`/`normalize` HTML→md + posted_at + level + match_score; `persist` upsert-by-id + cross-source dedup `(company, normalized_title)`; `pipeline.run_crawl` graceful per-site fail + `Run` record; `registry` config→scrapers). ITviec scraper implemented (real selectors); TopCV/VietnamWorks scaffolded to the same interface (disabled in config until real HTML snapshot); `FixtureScraper` for offline e2e. `cli crawl` wired (`--query`, `--no-robots`). No schema change (payload holds §3.1). 52 tests pass; verified live crawl→persist→Run on SQLite via fixture + real CLI path (ITviec fails gracefully w/o Playwright). *(chờ Codex review → push)*
- ✅ **Phase 4** — Web Dashboard MVP: React (Vite+TS+Tailwind, shadcn-style hand-rolled UI) "flight deck" dashboard. Backend additions: `POST /jobs/{id}/shortlist|skip` (state transitions + WS `job_updated` broadcast), stats enriched (`fresh`, `by_level`, `by_day`), `/jobs` search (`q`) + `fresh` filter, `JobDetailOut` (skills/description_md/is_fresh from payload), shared `timeutil` (+07 fixed offset). Frontend: Dashboard (KPI cards + signature "approach funnel" + BySource/ByDay charts via validated dataviz palette), Jobs (filter/search + shortlist/skip inline), Job detail (JD + skills + actions), realtime via `useWebSocket` (LIVE indicator + auto-refetch), dark/light theme. 58 py tests pass; `npm run build` clean (tsc+vite); verified live over HTTP (seeded SQLite → serve → curl /stats, /jobs, detail, q+fresh, shortlist transition, 401). *(chờ Codex review → push)*
- ⬜ Phase 4.5–8 — CV Studio → Tailor → Apply → Slack → polish (PLAN.md §9).

## Quyết định đã chốt (không tự đổi nếu user không yêu cầu)

- Apply = **hybrid theo kênh** (email full-auto, portal/LinkedIn human-in-the-loop).
- Nguồn = **ITviec + TopCV + VietnamWorks** lõi (pluggable, mở rộng theo tier — PLAN.md §5.1.1); không LinkedIn/Facebook.
- Giao diện = **Web Dashboard local** là chính, **Slack** phụ. DB = **PostgreSQL**.
- Chạy = **local**, tay hoặc cron nhẹ.
- Stack = Python (FastAPI + Playwright stealth + Claude API + Docker LaTeX) + React(Vite/TS/Tailwind/shadcn) + PostgreSQL + slack-bolt.
