# PHASES.md — nhật ký triển khai JobPilot

Chi tiết từng phase (scope, quyết định, bug chỉ lộ ra khi chạy thật).
Tách khỏi `CLAUDE.md` để file đó dưới ngưỡng context; bài học còn *đang áp dụng*
nằm ở `CLAUDE.md` mục "Nợ kỹ thuật" và "Thêm một site crawl mới".

## Nhật ký phase

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
- ✅ **Phase 7** — Slack (kênh phụ): `jobpilot/slack/` — **Slack là client thuần của REST API, backend không biết gì về Slack** (PLAN.md §10: 1 nguồn sự thật = Postgres, mọi action đi qua API → Web và Slack không thể lệch state). `client.py` (`JobPilotClient` gọi REST; nhận inject `httpx.Client` nên test chạy thẳng vào ASGI app thật), `blocks.py` (Block Kit builders **thuần**, không import SDK; `check_blocks` validate đúng limit Slack — 50 blocks / 3000 char section / 75 char label / 2000 char value; builder truncate thay vì để Slack trả 400), `events.py` (WS event → tin nhắn; **cố tình im lặng** với các transition thường để channel còn dùng được — chỉ post review/apply/failure), `app.py` (Socket Mode; nút = dispatch table `ACTIONS` → method của client; mirror WS chạy thread riêng, tự reconnect; degrade rõ ràng khi thiếu SDK/token). CLI `slack --api --web`. 256 test pass; verify live: client drive toàn bộ funnel qua HTTP thật (shortlist→tailor→approve→apply→confirm-submit), render đúng job/review/apply card (gap "Apache Kafka" hiện rõ, portal card có đủ field để dán), WS thật đẩy 2 event → mirror lọc còn 1 notification. ~~Chưa verify được: gửi thật lên Slack workspace~~ → **đã verify ngày 2026-08-08** trên workspace thật: app `jobpilot` (scope đúng một `chat:write`), Socket Mode + `connections:write`, digest lên channel, và **bấm nút Shortlist trên Slack thật** → `POST /jobs/{id}/shortlist` 200 → Postgres `DISCOVERED`→`SHORTLISTED` → dashboard đọc cùng state → Slack post ngược xác nhận. Khẳng định của `PLAN.md §10` giờ là quan sát được chứ không còn là thiết kế trên giấy.
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

- ✅ **Phase 10** — Tailor + apply rời request path, lên `TaskQueue`: `POST /jobs/{id}/tailor|edit|apply` giờ trả **202 + task**, tiến độ về qua WS `task_updated` (web có poll 1.5s làm lưới an toàn khi socket rớt). **Cái KHÔNG hoãn**: mọi thứ chỉ cần đọc DB là từ chối được vẫn là 409/422 **ngay trong request** (`service.check_tailorable` / `dispatcher.check_appliable` — sai status, hết edit round, chưa build CV). Hoãn một lỗi rõ ràng thành "chờ 1 phút rồi mới biết sai" là làm UX tệ đi, không phải làm nó async. Task body mở **session riêng** (session của request không sống lâu hơn request) và tự `queue.publish` các event domain (`job_updated`/`tailor_done`/`apply_done`) vì route đã return trước khi việc chạy — nhờ đó **guardrail fail giờ mới tới được Slack**: đường 422 cũ không broadcast gì cả. Guard **1 task / 1 job** (409) vì 2 vòng tailor sẽ tranh cùng build dir — guard nằm **trong `TaskQueue.submit(exclusive=True)`**, không phải ở route: check và insert phải cùng một lần giữ lock (xem bug 4). `Task.error_kind` (tên class exception) tách khỏi `error` để UI phân biệt `GuardrailViolation` (sự kiện truthfulness — hiện riêng, nói rõ "chưa ghi gì vào CV") với lỗi build/mạng. `progress` đặt tên đúng stage ("planning against the JD" / "building the PDF" / "writing the cover letter") — 2 stage này fail vì lý do hoàn toàn khác nhau. Task result cố tình **nhỏ** (`/tasks` trả 50 cái một lúc); plan/diff vẫn ở `cv_versions` qua `GET /review`. CLI giữ nguyên đồng bộ (terminal thì chờ là đúng). Web: hook `useTask` + component `TaskProgress`. 392 test pass; **verify live trên Postgres thật + Docker LaTeX thật + browser thật** (chỉ giả lệnh gọi Claude): `POST /tailor` **202 trong 34 ms** (trước là block cả vòng build), WS đẩy `queued→running→"planning against the JD"→"building the PDF"→job_updated→tailor_done→done`, PDF thật 1 trang; POST lần 2 khi đang chạy → 409; plan bịa "Golang/Terraform" → task **failed** + `error_kind=GuardrailViolation` + job FAILED + **không ghi thêm cv_version nào**; apply → 202 → `result=awaiting_user` + `job_updated SUBMITTING`; edit round 1→3 rồi round 4 bị chặn 409 ngay trong request; trang CV Review hiện pill TAILORING + card tiến độ chạy thật, không lỗi console.

  **5 bug chỉ lộ ra khi chạy thật / chạy full suite / khi review, đều đã có test ghim:**
  1. **`TestClient` dùng làm context manager chạy lifespan**, mà lifespan exit gọi `queue.shutdown()` → `ThreadPoolExecutor` **không restart được**. Sau test đó, mọi task submit tiếp theo nằm `queued` **vĩnh viễn** — UI thấy "đang chạy" nhưng không có gì chạy, và không có lỗi nào để đọc. Pool giờ **lazy + dựng lại sau shutdown**; task còn `queued` lúc shutdown bị đánh dấu `failed` ("cancelled — the queue shut down") thay vì nói dối là đang chờ.
  2. **SQLite in-memory + `StaticPool` = 1 connection dùng chung**, nên hết mô phỏng được Postgres ngay khi có thread thứ hai: worker đang mở transaction thì request thread `close()` session → **ROLLBACK nuốt luôn việc của worker**. Triệu chứng: apply task báo thành công mà job vẫn APPROVED. Test DB giờ là **file SQLite + WAL** → mỗi session một connection, giống thật. (Cùng họ với bài học "verify crawl phải chạy Postgres thật".)
  3. **`pypdf` là extra `[cv]` chưa cài** → `_pages_from_pdf` fallback regex không đọc nổi PDF của xelatex (object stream nén), builder image cũng không để lại `.log` → `pages = ... or 0`. `0` bị render thành badge đỏ "0 pages" trên một CV 1 trang hoàn toàn bình thường. `pages` giờ là `int | None`, `None` = *không biết* (UI ẩn badge, CLI nói "page count unknown"). "Không biết" và "0" là hai khẳng định khác nhau.
  4. **Guard "1 task / 1 job" đặt ở route là TOCTOU.** Route tailor/apply là `def` thuần → FastAPI chạy chúng trong threadpool, nên 2 request đồng thời cùng đọc `queue.active()` thấy trống rồi cùng `submit`. Verify thật: bắn **8 POST /tailor song song** → trước khi sửa nhiều task lọt, sau khi chuyển guard vào `submit(exclusive=True)` (check + insert + schedule trong **một** lần giữ lock) → đúng **1× 202, 7× 409, 1 task**. Cùng lock đó cũng đóng race `submit` vs `shutdown` (pool bị đóng giữa lúc dựng và lúc dùng → task kẹt `queued` vĩnh viễn → job đó 409 mãi mãi).
  5. **Exception "không lường trước" bỏ job kẹt ở TAILORING/SUBMITTING.** Service commit trạng thái đang-chạy *trước* phần chậm, nhưng chỉ đổi sang FAILED cho các lỗi nó biết (guardrail/build/SMTP). Một `KeyError` là job đứng mãi ở "đang tailor" mà chẳng có gì đang tailor. `_publish_job_status(settle=True)` ở nhánh lỗi giờ hạ trạng thái treo xuống FAILED — task vẫn giữ nguyên văn lỗi thật.

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

- ✅ **Phase 15** — Nhắc follow-up sau khi nộp: `apply/followup.py` + migration **0005** (`applications.next_followup_at`, `followup_stage`, index trên cột due). Pipeline trước đây kết thúc ở "submitted" rồi im lặng — mà đơn thường **không bị từ chối, chỉ bị quên**, vì nhớ follow-up là việc đúng ra công cụ này phải gánh. Nhịp hữu hạn: `first_nudge` (5 **ngày làm việc**) → `second_nudge` (+7) → `done` (hai lá thư không hồi âm đã là câu trả lời). Hai quyết định đáng bảo vệ: (1) **không tự gửi gì cả** — đến hạn thì hiện nhắc trên board, vì follow-up là thư gửi cho người đang cân nhắc mình, và thư rời máy mà mình chưa nhìn thấy đúng là thứ nguyên tắc 2 cấm; (2) **dry run không nợ ai cái gì** — không có gì rời máy thì không có ai để nhắc, và `NULL` nói điều đó thật thà hơn một cái hạn đã trôi qua. Dùng ngày làm việc chứ không phải ngày lịch: nhắc rơi vào Chủ nhật là nhắc bị đọc vào sáng Thứ hai với tâm trạng tệ hơn. API `GET /applications/followups`, `POST /applications/{id}/followed-up|stop-followups`. Web: card "N application worth chasing" trên trang Applications với 2 nút *I followed up* / *Let it go*. 491 test pass; `alembic upgrade head` sạch lên **Postgres 17 thật**, và verify live trọn nhịp qua API: due → `second_nudge` (rớt khỏi danh sách due) → `done` (hết hạn) → id lạ trả 404.

  **Bẫy gặp phải:** `is_due` so `next_followup_at` với `vn_now()` → **SQLite trả datetime naive còn Postgres trả aware**, nên so thẳng thì *nổ ở backend này và chạy ngon ở backend kia*. Ép cả hai vế về offset +07 cố định trước khi so — cùng họ với bài học "verify phải chạy Postgres thật, không chỉ SQLite".


- ✅ **Phase 16** — Diff giữa 2 version CV bất kỳ: `GET /cv/{scope}/diff?base=&target=` + card compare trong History của CV Studio. Đây là món nợ cuối của Phase 4.5 (`PLAN.md §9`), và nó rẻ đúng như đã hẹn — **không viết diff mới**: `tailor/diff.py:diff_documents()` vốn đã đi theo cấu trúc (reordered / hidden / trimmed / rewritten) thay vì so từng dòng, và `cv_versions` đã append-only từ đầu nên hai đầu so sánh luôn có sẵn. Frontend tái dùng luôn `review/DiffPanel.tsx` (thêm prop `title`/`action`, `changes` thành optional) — panel này sinh ra để trả lời đúng câu hỏi "cái gì đổi", không lý do gì vẽ lại lần hai.

  **Quyết định đáng bảo vệ — cùng một máy so, hai bộ từ vựng.** `diff_documents` trước đây nhúng cứng lời văn của tailor: section tắt đi được chú thích *"hidden from this CV to keep it to one page"*, summary đổi thì *"summary rewritten for this role"*. Đưa nguyên văn đó cho một so sánh v3 → v7 là **giải thích một sửa tay của người dùng thành một quyết định mà agent đã cân nhắc cho một job** — câu chú thích tự tin nhưng bịa, đúng họ với "sai dữ liệu *trông như đúng*" mà repo đã trả giá nhiều lần. Nên tách `DiffLabels`: `TAILOR_LABELS` (Master → tailored) và `VERSION_LABELS` ("section turned off", "summary rewritten"). **Chỉ lời văn được tham số hoá**, phần nhận diện cấu trúc dùng chung một hàm — hai bộ luật song song sẽ lệch nhau lúc nào không biết. Có test ghim rằng diff version **không** chứa "this role" / "one page".

  **`base`/`target` trong response là do server phát biểu lại**, không phải echo mù: UI đặt tiêu đề panel từ đó, nên nếu backend hiểu khác thứ frontend tưởng mình hỏi thì cái sai lộ ra ở tiêu đề chứ không âm thầm gán nhãn nhầm cho một diff đúng.

  **Bug bắt được trước khi ship: `CvDiff.changed` là `@property` thuần nên pydantic *không* serialize nó.** UI định dùng `diff.changed` để in "hai bản giống hệt nhau" — mà field đó sẽ luôn `undefined` ⇒ điều kiện luôn falsy ⇒ dòng đó không bao giờ hiện, im lặng, không lỗi console, test Python vẫn xanh vì phía Python `changed` chạy tốt. Chữa bằng `@computed_field` (một định nghĩa duy nhất, phía server) thay vì chép lại `order_changed || sections.some(...)` sang TS — hai bản sao của cùng một câu hỏi là mầm lệch pha. Type `CvDiff` bên TS ghi rõ field này do server tính.

  511 test pass; verify live qua **API + Postgres 17 thật** rồi lái trên trình duyệt thật (Playwright, không chỉ test): tạo một sửa thật (đổi summary, tắt Honors, đẩy Skills lên đầu) → `v2 → v3` trả đúng `rewritten` + `hidden` + `order_changed`, chiều ngược `v3 → v2` trả `"section turned on"`, `base==target` cho `changed=false`, version/scope lạ trả 404, `base=abc` trả 422. Trên UI: card compare hiện đúng, mặc định là hai version mới nhất, bấm Compare gọi đúng `?base=1&target=3`, panel hiện before/after gạch ngang + dải section order, **0 chỗ rò lời văn của tailor**, không lỗi console.

  **Hai bẫy khi verify (đều là bẫy môi trường, không phải code):**
  1. **API đang chạy sẵn ở :8000 là *code cũ*** — `openapi.json` không có route mới. Suýt kết luận "UI không gọi được API". Cùng họ với bẫy `pkill` của Phase 14: **hỏi server đang chạy xem nó có route đó không** (`/openapi.json`) trước khi tin bất cứ kết quả nào từ nó.
  2. **CORS chỉ mở cho `:5173`** (`api/main.py:ALLOWED_ORIGINS`), nên dev server dựng tạm ở cổng khác nhận "Failed to fetch" — trông hệt như lỗi ứng dụng. Đúng cách là chạy trình duyệt test với `--disable-web-security`, **không** nới `ALLOWED_ORIGINS` trong code chỉ để test chạy qua: cổng dev không phải thứ nên nở ra vì một lần verify.

  **Lưu ý dữ liệu:** verify chạy trên Master CV thật nên có thêm `v3` (bản sửa thử) và `v4` (rollback về nội dung `v2`) trong lịch sử. Nội dung hiện tại đã khôi phục **nguyên vẹn** — chính endpoint mới xác nhận điều đó (`v2` vs `v4` → `changed=false`). `cv_versions` là append-only nên hai row đó ở lại; đó là thiết kế, không phải rác.

- ✅ **Phase 17** — Cover letter thành *tài liệu*, không chỉ body email: template riêng `cv/templates/awesome_cv/cover_letter.tex.j2` + `apply/letter_pdf.py` + migration **0006** (`applications.cover_letter_pdf_path`). SKILL.md §2 bước 4 mô tả một `cover_letter.tex` từ đầu, nhưng tới giờ letter chỉ tồn tại dưới dạng text làm body email.

  **Điều đầu tiên phát hiện: `\cvletter` không tồn tại.** SKILL.md bảo "dùng class Awesome-CV `\cvletter` hoặc template riêng", nhưng `awesome-cv.cls` trong repo là **bản trim** — `grep -ci letter` trả về **0**. Không có `\recipient`, `\letteropening`, `\letterclosing`, không có env `cvletter`. Upstream Awesome-CV có đủ; bản vendor ở đây thì không. Nên đi đường "template riêng", dựng bằng đúng những macro class thật sự định nghĩa (`\makecvheader`, `\cvsection`, `cvparagraph`, `\makecvfooter`). Bài học: **đừng tin spec mô tả một macro tồn tại — grep class file trước.**

  **Preamble tách ra dùng chung** (`_preamble.tex.j2`): CV và letter cùng `\documentclass`, cùng `\definecolor{awesome}`, cùng khối `\name/\email/\github`. Nếu copy-paste thì đổi `theme.color` trong CV Studio sẽ đổi màu CV mà letter vẫn màu cũ — hai tài liệu gửi cùng một phong bì lại không khớp nhau. Refactor này được verify là **byte-identical**: render `cv.tex` trước/sau, diff chỉ có đúng mấy dòng comment mới thêm.

  **Bug LaTeX chỉ lộ ra khi đọc PDF thật.** Bản dựng đầu tiên compile sạch, 1 trang, không warning — và in ra `Ha Noi Dear Hiring Team at ACME`. Nguyên nhân: Jinja `trim_blocks=True` **ăn newline sau mỗi `%>`**, nên dòng trống mình đặt cạnh một tag để ngăn đoạn bị nuốt mất; `\vspace` rơi *vào trong* đoạn thay vì nằm giữa hai đoạn. Trong LaTeX dòng trống là thứ **có tải trọng**, mà nó lại vô hình khi review diff. Giờ mọi ngắt đoạn viết bằng `\par` tường minh, không phụ thuộc dòng trống. Test ghim đúng cặp đã hỏng. **Compile thành công không chứng minh layout đúng** — cùng họ với "test xanh không chứng minh parser đúng".

  **`build_cv(entry=...)` trước đây là một lời nói dối.** Image `csmith/awesome-cv-builder` có CMD **hardcode** `xelatex … cv.tex; mv $DIR/cv.pdf .`, mà `build_cv` không hề truyền `entry` cho docker — nó chỉ dùng `entry` để *kiểm tra file tồn tại* và *đoán tên PDF đầu ra*. Gọi `entry="cover_letter.tex"` sẽ build lại CV rồi fail vì không thấy `cover_letter.pdf`. Giờ tự viết command ra, `entry` mới có nghĩa.

  **Và một bug có sẵn phát hiện khi sửa chỗ đó**: command của image là `xelatex …; mv …; rm -rf …` **không có `set -e`**, nên LaTeX lỗi thì container **vẫn exit 0** (mã thoát do `rm` cuối quyết định) — dấu hiệu duy nhất của thất bại là *thiếu PDF*. Mà nếu build trước đó đã để lại `cv.pdf`, file cũ sẽ "trả lời thay": `build_cv` báo **thành công** và đưa về **nội dung cũ**. Đúng dạng "báo cáo thành công" mà repo sợ nhất. Sửa bằng cách xoá PDF đích trước khi chạy. Càng đáng sửa vì từ phase này letter và CV **chung một build dir**.

  **Test suite suýt mất tính hermetic.** Sau khi nối vào dispatcher, `pytest` **thật sự khởi động Docker** và ghi PDF vào `out/cv/itviec_1/` — vì `letter_pdf` tự suy ra build dir bằng `cv.compile.build_dir`, trong khi test chỉ patch `dispatcher.build_dir`. Hai ý kiến về cùng một đường dẫn, và ý kiến sai thắng. Sửa ở thiết kế: **caller truyền `dest` vào**, `letter_pdf` không tự đoán nữa. Cộng thêm stub `compile_letter` trong fixture, suite về lại 29s và không cần Docker.

  **Hai cột thay vì một**: `cover_letter_path` (text) và `cover_letter_pdf_path` (PDF) tách nhau vì chúng **hỏng tách nhau** — text có mà PDF không có (Docker tắt, LaTeX lỗi) là *đơn bị giảm chất lượng*, không phải *đơn thất bại*. Gộp một cột thì "build hỏng" trông y hệt "không có letter nào". Lý do cụ thể nằm ở `meta.letter.pdf_error`, và board hiện nó ra như một ghi chú xám chứ không phải lỗi đỏ. Cùng họ `pages=None` vs `pages=0`.

  **Đơn vẫn gửi khi PDF hỏng** — CV đã build xong rồi, giữ đơn lại vì cái đính kèm phụ không dựng được là phạt nhầm người. Email đính kèm letter PDF **chỉ khi nó thật sự build**, không bao giờ đính file cũ hoặc file hỏng.

  531 test pass. Verify thật: `alembic upgrade head` → **0006** lên Postgres 17 (và `downgrade 0005` → `upgrade` round-trip sạch); build PDF thật qua Docker LaTeX rồi **đọc lại text layer** bằng pdfminer để chắc `&`, `%`, `_`, `#` sống sót đúng; chạy trọn `apply_job` trên **Postgres + Master CV thật** → `awaiting_user`, cả 2 đường dẫn ghi đúng row, `pdf_error=None`. Dữ liệu verify (job `itviec:phase17-verify` + build dir) đã xoá sạch sau khi xong.

- ✅ **Phase 18** — Outcome tracking: cái gì xảy ra **sau** khi nộp. `apply/outcome.py` + migration **0007** (`applications.outcome_stage` + bảng `application_events`). Đây là mở màn của roadmap mở rộng `PLAN.md §9.1`, dựng sau khi khảo sát [ai-job-search](https://github.com/MadsLorentzen/ai-job-search), [career-ops](https://github.com/santifer/career-ops), [jobsync](https://github.com/Gsync/jobsync) — cả ba đều có phần này, còn JobPilot thì pipeline **kết thúc ở `SUBMITTED`**: nộp xong là mù, không biết nguồn nào thực sự ra phỏng vấn, và mọi câu hỏi "cách tìm việc này có hiệu quả không" đều không có dữ liệu để dựa vào.

  **Quyết định 1 — `JobStatus` không thêm giá trị nào.** `job_status` là Postgres enum: thêm value phải `ALTER TYPE … ADD VALUE`, **không chạy được trong transaction block**, và kéo theo `web/src/lib/statuses.ts`, funnel, `StatsOut.by_status`, `slack/events.py:_QUIET_STATUSES`. Về mô hình cũng sai: `JobStatus` là vòng đời *trước khi nộp* của một **job**, outcome là chuyện xảy ra với một **đơn**. Một job `SUBMITTED` vẫn `SUBMITTED` dù sau đó offer hay bị từ chối. Có test ghim `"REJECTED" not in by_status`.

  **Quyết định 2 — vừa cột denormalized vừa bảng event append-only.** `GET /applications` trả tới 200 row và đã join `Job`; bắt mỗi row subquery lịch sử thì 1 JOIN thành 200 correlated subquery. Nên `Application.outcome_stage` phục vụ board với chi phí 0, còn `application_events` là nhật ký không xoá. Đúng pattern `cv_versions` đã dùng.

  **Quyết định 3 — đếm thống kê từ *event*, không từ `outcome_stage`. Đây là chỗ dễ sai một cách im lặng nhất của cả phase.** Một đơn đã phỏng vấn 2 vòng *rồi mới* bị từ chối chỉ hiện ra là `rejected`; đếm interview theo cột đó thì interview rate báo cáo số đơn đang **kẹt** ở vòng phỏng vấn chứ không phải số đơn **đạt tới** vòng phỏng vấn — một con số **tụt xuống khi việc tìm việc đang tiến triển tốt**. Nên `/stats` trả hai bộ: `current` (đếm theo `outcome_stage`, để render) và `reached` (`COUNT(DISTINCT application_id)` trên event chưa retract, để tính tỉ lệ). Có test ở cả tầng unit lẫn HTTP ghim đúng ca này. Thêm một điều chỉnh nhỏ cùng tinh thần: **lời mời phỏng vấn *là* một hồi âm** — không ai gõ "họ trả lời" rồi gõ tiếp "họ mời phỏng vấn" cho cùng một email, nên nếu không gộp thì việc được mời phỏng vấn sẽ **làm tụt** reply rate.

  **`event_type` là `String(32)`, không phải Postgres enum** — tập giá trị sẽ còn nở ra (Phase 19 mang thêm phân loại thư từ inbox), và mỗi value mới sẽ tốn một migration `ALTER TYPE` vụng về. Hợp lệ được ép ở tầng Pydantic (`Literal`), nơi giá trị sai là 422 chứ không phải 500.

  **`occurred_at` tách khỏi `recorded_at`**: time-to-reply (Phase 20) đo từ lúc nhà tuyển dụng *thật sự* trả lời, không phải lúc mình kịp gõ vào — và Phase 19 thì gõ vào muộn vài ngày theo đúng định nghĩa.

  **Ghi outcome = dừng follow-up**, luôn luôn. Cadence sinh ra để đuổi theo sự im lặng; biết được bất cứ điều gì — kể cả một lời từ chối — thì không còn gì để đuổi, và một nhắc nhở đi thúc công ty vừa nói "không" là kiểu prompt làm người ta thôi tin công cụ. **`dry_run`/`failed` bị từ chối bằng 409**: không có gì rời khỏi máy thì không có ai để trả lời, và một outcome bịa ra ở đó làm hỏng đúng cái mẫu số mà dashboard sẽ chia. **`ghosted` do user tự gọi tên**, không suy ra từ bộ đếm ngày — một sự im lặng mình chưa buông không giống một lời từ chối, và chỉ mình biết mình đang ở tình huống nào (cùng lý do follow-up không tự gửi).

  **Bấm nhầm thì *retract*, không xoá**: row ở lại (gạch ngang trên card), `outcome_stage` lùi về event còn sống mới nhất — xếp theo `id` chứ không theo `occurred_at`, vì một chỉnh sửa ghi lùi ngày không nên thắng thứ mình vừa ghi sau đó.

  573 test pass. Verify thật: `alembic upgrade head` → **0007** lên **Postgres 17** (round-trip `downgrade -1` → `upgrade` sạch, kiểm tận `information_schema`), lái trọn bộ endpoint trên API thật, rồi lái **UI thật bằng Playwright** trên board + dashboard. Dữ liệu verify đã xoá sạch khỏi DB thật.

  **Ba thứ chỉ lộ ra khi chạy thật:**
  1. **Guard chống double-click bằng React *state* là vô dụng.** Hai click trong cùng một tick đều đọc `busy === false` vì React chưa kịp re-render giữa hai lần — nên click thứ hai lọt và ghi một event trùng. Phải là `useRef`. Không ảnh hưởng tỉ lệ (chúng đếm *đơn*, không đếm *event*), nhưng một dòng trùng trong cái lịch sử mà toàn bộ giá trị của nó là *đọc được* thì có.
  2. **Ô KPI "Success 100% · 2/2 landed" có sẵn bỗng thành lời nói dối** khi hàng outcome thật nằm ngay dưới nó: nó chỉ đo *dispatch có trót lọt không*, mà lại ngồi trên một đơn vừa bị từ chối. Đổi thành **"Sent OK · left the machine"**. Chữ có sẵn từ trước, nhưng chính thay đổi này làm nó đọc thành sai.
  3. **SQLite đánh rơi offset khi đọc lại `DateTime(timezone=True)`** — cùng họ bẫy `followup._aware` của Phase 15. Test không nới lỏng mà ghim đúng điều phải đúng trên **cả hai** backend: 09:00 gõ vào vẫn là 09:00 đọc ra, không thành 09:00 UTC = 16:00 local.

  **Review gate bắt được 2 lỗi mà 573 test xanh không thấy** (`phase-reviewer` trên diff thật):
  1. **`answered = max(reached[replied], reached[interview], …)` — sai số học.** Các bucket đó đếm **theo loại event**, nên một đơn được trả lời qua email và một đơn khác được gọi điện thẳng mời phỏng vấn cho ra `{replied: 1, interview: 1}`, mà `max` đọc thành **1 đơn có hồi âm** trong khi thật ra là **2** → dashboard báo *reply rate 50%* cho một đợt tìm việc mà **ai cũng đã trả lời**. Lỗi trốn được vì mọi test khác đều dùng **một** đơn duy nhất, nơi `max` tình cờ đúng. Phải là `COUNT(DISTINCT application_id)` riêng trên tập `ANSWERED_BY = {replied, interview, offer, rejected}` (`withdrawn`/`ghosted` không nằm trong đó: **mình** quyết, không phải họ). Đúng họ "báo cáo thành công nhưng sai" mà repo sợ nhất — và là lý do một `max()` trông vô hại đáng bị nhìn kỹ.
  2. **Retract hết outcome thì follow-up kẹt `done` vĩnh viễn.** `record_outcome` đặt `followup_stage=DONE`; `retract_outcome_event` chỉ lùi `outcome_stage`. Bấm nhầm rồi rút lại ⇒ board hỏi "what happened?" nhưng nhắc nhở **tắt luôn**, không route nào bật lại được — mất nhắc cho một đơn **chưa từng được trả lời**. Sửa tận gốc thay vì thêm nút: mỗi event tự nhớ `prev_followup_stage`/`prev_followup_at` (migration 0007 chưa lên `main` nên thêm cột không tốn gì), retract hết thì khôi phục lại đúng chỗ đó.

     **Neo vào đâu là câu hỏi khó hơn nó trông.** Bản đầu neo vào *event đầu tiên* — sai: rút một lần bấm nhầm → nhắc quay lại → **bạn nhắc thật** (`second_nudge`) → ghi một outcome thật → rút nốt ⇒ cadence bị kéo về `first_nudge`, tức bảo bạn đi nhắc lại công ty **bạn đã nhắc rồi**, và tặng thêm một nhịp thứ ba cho một cadence cố tình chỉ có hai. Neo đúng là **event gần nhất thật sự bắt gặp cadence còn sống** (`prev_followup_stage IS DISTINCT FROM 'done'`) — không phải event đầu, cũng không phải event cuối. Dùng `is_distinct_from` chứ không `!= 'done'`: `prev_` có thể `NULL`, mà `NULL != 'done'` trong SQL là `NULL` ⇒ hàng đó bị loại **im lặng**. Ba test ghim: event không tắt gì thì bị bỏ qua, nhắc thật thì sống sót, và rút không theo thứ tự vẫn đúng.

  Cộng một nit: `ApplicationEventOut.occurred_at`/`recorded_at` khai `| None` trong khi cột là `NOT NULL` — mô tả sai contract cho phía tiêu thụ. 581 test pass sau khi sửa; verify lại cả ba trên **Postgres + API thật** (`answered` 1 → **2**, `reply_rate` 0.5 → **1.0**; retract hết ⇒ đơn quay lại danh sách follow-up due; và kịch bản nhắc-thật-rồi-rút giữ đúng `second_nudge`).

- ✅ **Phase 19** — Inbox sync: đọc thư nhà tuyển dụng và **đề xuất** outcome. `apply/inbox.py` + migration **0008** (`inbox_suggestions`) + `crawler/mailbox.py` đọc được thư không biết trước người gửi. Phase 18 cho đơn mang outcome; ghi tay được chừng hai tuần rồi thôi, và con số thành bản ghi về độ chăm chỉ gõ phím chứ không còn về đợt tìm việc. Câu trả lời nằm sẵn trong hộp thư.

  **Thứ tự xử lý CHÍNH LÀ thiết kế riêng tư, không phải tối ưu.** Fetch → ghép **cục bộ bằng Python thuần** → thứ gì không thuộc về đơn nào thì **dừng ngay tại đó** → chỉ phần còn lại mới tới Claude. Thư ngân hàng, thư riêng, newsletter không bao giờ rời khỏi máy. Có test ghim đúng tính chất này (`test_unmatched_mail_is_never_handed_to_the_classifier` assert `engine.seen == ["1"]`), nên nếu ai đảo thứ tự thì test đỏ.

  **Bốn mức tin cậy, hiển thị ra UI chứ không giấu**: `thread` (thư trích đúng `Message-ID` mình gửi — chắc chắn), `address` (đúng địa chỉ đã nộp), `domain` (đồng nghiệp cùng domain trả lời — ca thường gặp nhất), `company` (domain *trông giống* tên công ty — yếu nhất, và là thứ **duy nhất** dùng được cho đơn portal/LinkedIn vì mình chưa từng gửi mail nào để họ reply). Card nói thẳng "guessed from the sender's domain" thay vì để người dùng tự đoán.

  **Để `thread` tồn tại được thì phải tự đóng dấu `Message-ID`** trong `OutgoingEmail.as_message()` và ghi vào `meta.email.message_id` — trước đây để mặc SMTP server sinh, tức là một giá trị mình **không bao giờ nhìn thấy**, nên không thể so. Đóng dấu cả khi dry run, để row nói rõ "không có thread nào để ghép" thay vì để người đọc tự hỏi.

  **Bảng riêng, không nhét vào `application_events`.** Đề xuất không phải là chuyện đã xảy ra. Nếu gắn cờ trong event log thì mọi phép đếm ở `outcome_counts` phải nhớ loại nó ra — mà phase ngay trước đã ship đúng một bug kiểu "một aggregate quên mất một phân biệt".

  **Guardrail: `quote` phải có thật trong thư.** Card hiện nguyên câu để bạn bác được cái nhãn chỉ bằng cách đọc một dòng; một classifier diễn giải lại sẽ khiến phép kiểm tra đó bất khả thi mà vẫn *trông như* bằng chứng. Kèm phòng thủ prompt injection: JD/mail là **dữ liệu, không phải chỉ thị**.

  **Chỉ đề xuất 4 loại** (`replied`/`interview`/`offer`/`rejected`). Nhà tuyển dụng không thể *rút đơn* hộ bạn, và không ai gửi mail báo rằng họ đang ghost bạn — hai cái đó vẫn thuộc quyền bạn tự khai. Thư "chúng tôi đã nhận hồ sơ" là `auto_ack`, **không phải** `replied`: máy trả lời không phải người trả lời.

  612 test pass. Verify thật: `0008` lên **Postgres 17** (round-trip downgrade/upgrade, soi `information_schema` + unique constraint), đọc **hộp thư Gmail thật** qua đường `senders=()` mới (15 thư: 15 có `Message-ID`, 14 có text part), chạy trọn `sync_inbox` trên **Postgres thật + mail thật**, rồi lái UI thật bằng Playwright (accept → outcome + follow-up biến mất; dismiss → không hiện lại). Dữ liệu verify đã xoá sạch.

  **Ba thứ chỉ lộ ra khi chạy thật:**
  1. **Verdict bị loại vì quote không có thật thì không lưu lại gì cả** ⇒ lần sync sau thư đó lại "mới", lại gọi Claude, **trả tiền vô hạn** cho một câu trả lời không bao giờ được hiển thị. Chạy sync hai lần trên hộp thư thật mới thấy: `pass 2` vẫn `classified: 1`. Giờ lưu status `unusable` (không bao giờ đề xuất, nhưng đã biết rồi). Test xanh không thấy vì test chỉ chạy sync **một** lần.
  2. **Danh sách từ nhiễu tên công ty là ASCII, tên công ty Việt Nam thì có dấu** — "Công ty TNHH Beta" giữ lại `công` như thể đó là phần đặc trưng của tên. Mà domain thì **không bao giờ** có dấu, nên phải fold về ASCII trước khi so. Test bắt được ngay lần chạy đầu.
  3. **Card Applications vỡ cả board khi `meta` thiếu một key** (`email.attachments.length` trên `undefined` → React unmount toàn bộ). `meta` là JSONB do bất kỳ phiên bản dispatcher nào ghi; một row thiếu key không được phép làm trắng cả trang. Guard bằng optional chaining, và panel email chỉ vẽ khi thật sự có địa chỉ — trước đó nó hiện một mũi tên "→" rỗng trông như hỏng.

  **Review gate bắt thêm 3 lỗi** (`phase-reviewer`):
  1. **`mail_key` không clamp trước khi ghi vào `String(512)`** — đúng lại bẫy "SQLite không enforce VARCHAR, Postgres có" mà repo đã trả giá ở `normalize._fit()`, chỉ khác tên field. `Message-ID` do máy chủ của người lạ sinh và RFC 2822 cho phép dài gần cả dòng header; reviewer reproduce được id 521 ký tự. Nổ giữa flush ⇒ mất cả batch. **Cắt là sai ở đây** (khác với `label`): hai id trùng 512 ký tự đầu sẽ biến thành *một* thư và một cái không bao giờ được đọc. Nên id quá dài thì **hash** — vẫn duy nhất, vẫn có biên; id bình thường giữ nguyên để bảng còn đọc được.
  2. **`accept_suggestion` có hai commit** — `record_outcome` commit outcome rồi mới tới `found.status = ACCEPTED` + commit lần hai. Crash vào khe giữa ⇒ event đã ghi mà suggestion vẫn `pending`, lần bấm sau ghi event **lần thứ hai**. Sửa bằng cách đánh dấu **trước** rồi để `record_outcome` commit cả hai trong cùng một transaction. Test cũ chỉ cover double-click tự nguyện, không cover crash-and-retry.
  3. **Route `dismiss` trả `SuggestionOut` không kèm job** ⇒ `job_title`/`company` rỗng, cùng một kiểu dữ liệu mà hai endpoint trả khác nhau — thứ không ai nhận ra cho tới lúc có chỗ render trắng.

  Cộng một nit: type `verdict` bên TS chỉ có `OutcomeType`, trong khi cột còn ghi `auto_ack`/`unrelated`. 614 test pass sau khi sửa.

- ✅ **Phase 20** — Chạy model trên chính máy mình: `jobpilot/llm/ollama.py` + engine Ollama cho cả ba lệnh gọi LLM. Xuất phát từ một câu hỏi rất thẳng của user — *"task này có thật sự cần model tốn tiền không?"* — và câu trả lời hoá ra **khác nhau cho từng lệnh gọi**, nên config chọn provider **theo từng việc** chứ không phải một công tắc chung.

  **Lý do thật không phải tiền, mà là riêng tư.** Đo được: một lần tailor ≈ **$0.057**, một email ≈ $0.005 (Opus 4.8, JD ~8.000 ký tự). 100 tailor + 300 email ≈ **$7**. Tiền không phải vấn đề. Vấn đề là input của tailor là **toàn bộ Master CV** — họ tên, số điện thoại, lịch sử làm việc — và điều khoản **free tier** của Gemini cho phép nhà cung cấp train trên input/output. Với một repo mà nguyên tắc 3 là *"không commit thông tin cá nhân"* thì gửi CV lên free tier còn tệ hơn commit vào private repo. Local thì CV **không rời khỏi máy** — nó thắng cả Claude về nguyên tắc 3, và miễn phí chỉ là hệ quả.

  **Constrained decoding là thứ làm chuyện này khả thi.** Ollama nhận JSON Schema ở `format` rồi biến thành *grammar giải mã* — model không thể phát ra token phá schema. Đúng chỗ model nhỏ yếu nhất thì bị loại bỏ về mặt cơ học, còn lại đúng chỗ guardrail đã được xây để canh. `$defs`/`$ref` của Pydantic được **inline trước khi gửi** (`flatten_schema`): reference là góc yếu nhất của schema-to-grammar.

  **Vòng guardrail dùng chung, không fork.** `_GuardedTailor` giữ dựng-prompt + check + một vòng sửa; engine chỉ cung cấp `_parse`. Có test ghim `OllamaTailorEngine.tailor is ClaudeTailorEngine.tailor`. Đây là bài học Phase 16 (*"đừng fork hàm diff"*) áp vào chỗ nguy hiểm hơn: model yếu **cần** vòng retry đó nhiều hơn Claude, nên hai bên bắt buộc phải là **cùng một** vòng retry.

  **Kết quả đo thật trên RTX 3060 Laptop (6 GB VRAM), `qwen2.5:7b`:**

  | Lệnh gọi | Kết quả | Kết luận |
  |---|---|---|
  | **classify** (1 email → 6 nhãn + trích 1 câu) | **5/5 nhãn đúng**, ~2s/thư sau lần nạp đầu (62s) | ✅ bật local |
  | **tailor** (xếp lại index + 1 đoạn summary) | **0/4** sau **ba** vòng vá prompt | ❌ giữ Claude |

  **Tailor thất bại theo một kiểu rất cụ thể, và nó dạy được nhiều thứ.** Vòng 1: `section_order` thiếu key. Vòng 2 (sau khi vá): dùng `item_order` cho section kiểu entries. Vòng 3 (sau khi vá tiếp): **đảo chiều** — dùng `entry_order` cho section kiểu bullets. Nó không hết nhầm mà chỉ **hoán vị** chỗ nhầm ⇒ 7B không giữ nổi ánh xạ *section type → order field*, kể cả khi được liệt kê tường minh từng dòng. Quan trọng: đây **không** phải lỗi "bịa nội dung" — guardrail truthfulness không hề bị chạm tới; nó là lỗi *điều hướng schema*.

  **Hai lỗi prompt tìm ra nhờ chạy model yếu, và cả hai đều có lợi cho Claude:**
  1. `section_order` có cửa thoát "để rỗng = giữ nguyên" **trong schema** nhưng prompt **chưa bao giờ nói**. Model muốn diễn đạt "chỉ mấy mục này quan trọng" nên trả về danh sách một phần — đúng thứ duy nhất không hợp lệ.
  2. **`retry_prompt` không hề sửa cái vừa hỏng.** Nó liệt kê vi phạm rồi khuyên về *index và summary* — trong khi cái vỡ là `section_order`. Vòng "sửa lỗi" trỏ sang luật khác. Claude ít lộ vì nó hiếm khi sai lần đầu, nhưng đây là bug thật của vòng retry. Giờ `_REMEDIES` nhắc lại đúng luật đã vỡ.

  Outline vốn đã in `type=experience` / `type=bullets`, nhưng prompt không giải thích nhãn đó nghĩa là gì — đã bổ sung bảng ánh xạ. Model mạnh suy ra được, model yếu thì không, và việc nói ra không tốn gì.

  **Cũng sửa một luật của chính mình, do chạy thật mới thấy**: `check_verdict` bắt buộc có quote cho **mọi** verdict trừ `unrelated`. Nhưng `auto_ack` cũng **không bao giờ hiện lên card** — nó chỉ được ghi rồi bỏ qua. Model trả lời `auto_ack` **đúng**, không kèm quote, và guard đem câu trả lời đúng đó xếp vào loại "classifier hỏng". Quote tồn tại để user bác cái nhãn *được hiện ra*; không hiện thì không có gì để bác. Giờ chỉ `PROPOSABLE` mới bắt buộc có bằng chứng.

  **Và một test tự phơi mình ra**: `test_missing_tokens_produce_a_readable_error` chỉ ép rỗng **một** trong ba khoá Slack, hai khoá kia rơi xuống `.env` thật — nên nó xanh chỉ vì máy dev *chưa* cấu hình Slack, và đỏ ngay khi user điền token. Test không được phụ thuộc vào việc máy chạy nó có cấu hình gì.

  Mặc định vẫn là `claude` cho cả ba: đổi model của user trong im lặng là đổi nội dung đơn họ gửi đi.

- ✅ **Phase 20b** — Một tầng provider thay cho hai backend rời: `jobpilot/llm/` giờ có `base.py`
  (hợp đồng `StructuredClient`), ba client (`claude` / `openai` / `gemini`), `registry.py`
  (dict `PROVIDERS`), `schema.py`, `pricing.py`, `usage.py`, `stats.py`, `bench.py`.
  **Ollama bị gỡ hẳn** theo yêu cầu user; `classify` chuyển sang cloud.

  **Lý do thật không phải "dọn dead code".** Phase 20 để ngỏ bốn hướng cho tailor local, và
  câu trả lời hoá ra nằm ở một dòng khác trong nợ kỹ thuật: *Anthropic hết credit*. Cộng với
  `tailor` local 0/4 ⇒ **không có backend nào chạy được cho tailor**. Multi-provider là lối
  thoát khỏi tình trạng đó; "rẻ hơn" thì không phải lý do — tổng chi phí là **$7** cho 100
  tailor + 300 email.

  **Cái đã mất, ghi thẳng ra:** `classify` từng chạy local 5/5 và nội dung thư nhà tuyển dụng
  **không rời khỏi máy**. Giờ nó đi qua API của provider. Docstring ở `apply/inbox.py` đã sửa
  cho khớp — để nguyên là để lại một lời hứa không còn đúng. Phần *vẫn* đúng và vẫn phải đứng
  đầu: thư **không khớp đơn nào** dừng lại trong máy, không bao giờ tới API.

  **Sáu class engine → ba.** Trước đó `_get_client()` của Anthropic bị chép nguyên văn **3 lần**
  và `letter.py` giữ **hai bản** vòng retry (Claude / Ollama) gần giống nhau — đúng thứ
  `_GuardedTailor` được viết ra để tránh, nhưng letter không dùng nó. Thêm 2 provider theo lối
  cũ là **6 class + 6 bản copy**. Giờ mỗi task một engine cầm một `StructuredClient`, và bất
  biến "mọi backend đi qua cùng một vòng retry" do **không còn gì để fork** giữ, chứ không phải
  do một test giữ (test cũ `OllamaTailorEngine.tailor is ClaudeTailorEngine.tailor` mất chỗ
  đứng vì lý do tốt).

  **Ba provider không nhận cùng một JSON Schema** — tra tài liệu chính thức, không đoán:
  OpenAI strict **có** hỗ trợ `$ref`/`$defs` (kể cả đệ quy), giới hạn 10 tầng / 5.000 property /
  1.000 enum, không hỗ trợ `allOf`/`not`/`if-then-else`; Gemini chỉ liệt kê một **subset** và
  cảnh báo schema lồng sâu có thể bị từ chối, nên `flatten_schema` (viết cho Ollama) được giữ
  lại và dùng cho Gemini. `strictify` cho OpenAI có một bẫy đáng ghi: "mọi field phải nằm trong
  `required`" **không** có nghĩa bỏ optional — optional phải nới thành **nullable**, nếu không
  model bị *ép bịa* ra `summary`. Đọc sai chỗ này là biến một luật về hình dạng thành một lệnh
  bịa nội dung.

  **SDK đúng tên:** Gemini là `google-genai` (`from google import genai`). `google-generativeai`
  **đã deprecated** (hết hỗ trợ 2025-08-31) và hai cái cách nhau một chữ trong `pip install`.

  **Đo thay vì đoán.** Bảng `llm_calls` (migration 0009), **một row mỗi round** — kể cả round bị
  guard từ chối, kể cả lượt gọi hỏng. Lý do: một backend rẻ mỗi lượt mà phải retry một nửa số
  lần thì **không** rẻ, và một bảng chỉ giữ round được nhận sẽ làm nó trông đẹp nhất ở đúng cột
  người ta sort. `GET /stats/llm` + `jobpilot llm stats` + `jobpilot llm bench`.

  **Hai luật "không biết ≠ hỏng" áp vào số liệu:**
  - `cost_usd` **NULL** khi model không có trong `pricing.PRICES`, không phải `0.00`. Bảng giá cũ
    đi bằng cách nằm yên, nên trường hợp không biết giá là **bình thường**, không phải ngoại lệ —
    và $0.00 sẽ khiến backend ít biết nhất trông rẻ nhất. `unpriced_rounds` đi kèm mọi tổng.
  - Dưới `MIN_SAMPLE = 10` thì **không hiện %**, hiện `n=<count>`. 3 lượt 2 lỗi không phải "33%";
    tỉ lệ mời người ta so hai backend trên 3 lượt mỗi bên. Cùng luật `outcome_counts` đã theo.

  **Cảnh báo dữ liệu phải hẹp mới có người đọc.** Tra terms: Anthropic / OpenAI / Gemini **trả
  tiền** đều không train trên input API. Chỉ **Gemini free tier** là có, và terms ghi thẳng *"Do
  not submit sensitive, confidential, or personal information to the Unpaid Services"* — trong
  khi `tailor`/`letter` gửi **cả Master CV**. Không đọc được tier từ API key ⇒ `llm.gemini_paid_tier`.
  Là **thông báo, không phải cổng chặn** (user chọn "cho hết, cảnh báo rõ").

  **Bug chỉ lộ ra khi chạy thật — và nó lộ ra ở đúng chỗ mỉa mai nhất.** `llm bench` chạy xong,
  in kết quả, và **mất sạch** row telemetry: bench dùng `Applied(0, ...)` (application giả), FK
  `llm_calls.application_id` vỡ, và `record()` *nuốt lỗi theo thiết kế* nên không ai biết. Tức
  là lệnh mà toàn bộ nhiệm vụ là **tạo ra một phép đo** đã lặng lẽ vứt phép đo đi. Sửa hai lớp:
  `ModelClassifier` truyền `app.application_id or None`, và `record()` ghi **hai lần** — có link,
  rồi nếu vỡ thì không link. Mất cái liên kết còn hơn mất con số. Bài học: *"nuốt lỗi để không
  làm hỏng việc chính"* đúng, nhưng nó cũng chính là thứ giấu lỗi khỏi mắt mình.

  **Console Windows là cp1252.** Em dash trong chuỗi `print()` làm `UnicodeEncodeError` và giết
  cả lệnh. Mọi chuỗi in ra terminal giờ ASCII (docstring thì không sao). `cli.py:326` và `:446`
  vẫn còn hai em dash **có sẵn từ trước** — cùng lỗi tiềm ẩn, chưa sửa vì ngoài phạm vi.

  **Hai thứ review gate bắt được, ghi lại vì cả hai đều thuộc loại "chỉ sai một chiều":**
  - `first_try_rate` **tính sai** khi một task retry rồi *vẫn* hỏng. `first_try = successes -
    retries`, nhưng `retries` đếm **mọi** round-2 trong khi `successes` không hề chứa task hỏng
    ⇒ một task hỏng triệt tiêu một task first-try không liên quan. 8 sạch + 1 retry-ok +
    1 retry-fail cho **70%** thay vì 80%; 5 sạch + 5 retry-fail cho **0%** thay vì 50%, và
    `max(..., 0)` **che** lỗi chứ không sửa. Luật rút ra: *hai vế của một phép trừ phải đang đếm
    cùng một tập*. Sai theo hướng làm backend trông tệ hơn thực tế — trong đúng bảng dùng để
    chọn backend. Đã ghim 2 test.
  - `LlmCall.ok` mặc định `True` trong khi `CallLog.accepted` mặc định `False` với lý do đã viết
    rõ ("một row chưa ai set kết quả không phải là một thành công không ai nhận được"). Hai mặc
    định ngược nhau cho cùng một khái niệm. Đổi cả model lẫn `server_default` về `false`.

  **Thay đổi hành vi nhỏ, ghi ra vì nó không tự hiện:** `ClaudeClassifier` cũ **không** truyền
  `thinking`; `ClaudeClient` dùng chung thì có (`adaptive`). Giữ nguyên một call shape thay vì
  thêm một knob theo task vào hợp đồng dùng chung — `adaptive` nghĩa là model tự quyết, và với
  6 nhãn thì nó gần như không nghĩ. Nếu sai thì **chính bảng phase này thêm** sẽ cho thấy:
  `llm stats` đo output token và latency của `classify` tách riêng.

  **Blocker đổi nghĩa:** không còn "ollama serve có chạy không" mà là "provider đang cấu hình đã
  có API key chưa". Nó nằm trong `get_engine()` của route chứ **không** trong route body — để
  test tự cấp engine không bị đòi key, đúng cái bẫy `test_missing_tokens_produce_a_readable_error`
  đã dính ở Phase 20 (xanh/đỏ tuỳ máy chạy có cấu hình gì).

  **Verify thật:** 637 test, ruff + `tsc` sạch; `alembic upgrade head` → `downgrade -1` → `upgrade`
  trên **PostgreSQL 17 local**; `llm bench --task classify` chạy đầu-cuối và ghi 5 row vào
  `llm_calls` thật; `GET /stats/llm` trả đúng (`first_try_rate=None`, `n=5`, `cost_usd=None`,
  `unpriced_rounds=5`); trỏ `llm.tailor: gemini` + `gemini_paid_tier: false` → `POST /jobs/../tailor`
  trả **409** kèm lý do đọc được, và cảnh báo về Master CV hiện đúng.
  **Chưa verify được: một lượt gọi *thành công*.** Anthropic hết credit, `OPENAI_API_KEY` bị từ
  chối 401, chưa có `GOOGLE_API_KEY` — nên **shape request của OpenAI/Gemini chưa đối chiếu với
  API thật** (401 xảy ra trước khi request được validate). Đó là việc đầu tiên khi có key.

- ✅ **Phase 20c** — Quản lý model từ Web, và ba luật user đặt: **(1) không leak key, (2) đổi được
  model + có dashboard đo, (3) mặc định model rẻ nhất mà vẫn hiệu quả.** Trang `/models`
  (`web/src/pages/Models.tsx`) + `llm/redact.py` + `llm/registry.list_models` + `llm.budget_usd`.

  **Cả ba provider đã gọi thật thành công** (trước đó chưa verify được lượt nào). Đo trên bộ 5
  email của Phase 20, **tất cả 5/5**:

  | model | 5 email | p50 |
  |---|---|---|
  | `gpt-4o-mini` | **$0.0005** | 1324ms |
  | `gemini-3.1-flash-lite` | $0.0007 | **705ms** |
  | `gemini-3.5-flash-lite` | $0.0010 | 773ms |
  | `gpt-4.1-mini` | $0.0013 | 1185ms |
  | `claude-haiku-4-5` | $0.0043 | 1256ms |
  | `gemini-3.5-flash` | $0.0187 | 2110ms |

  Rẻ nhất **và** nhanh nhất là `gemini-3.1-flash-lite` ⇒ đã đặt cho `classify` **qua chính cái
  picker trên web**, tức là vừa test tính năng vừa áp dụng luật 3. `tailor` trên
  `claude-opus-4-8` chạy job thật: **2/2 qua guardrail ngay vòng đầu**. Ghi chú: `gemini-3.5-flash`
  đắt gấp ~27× bản lite vì **thinking token tính giá output**.

  **Leak thật, tìm được vì chạy thật.** Key OpenAI sai ⇒ provider trả *"Incorrect API key
  provided: sk-proj-…"*, và chuỗi đó đi thẳng vào `llm_calls.error`, ra CLI, ra API. Nên scrub
  đặt ở **chỗ tạo ra lỗi** (`LlmError.__init__` + `CallLog`), không phải ở từng nơi lỗi đi tới —
  có một chỗ đầu và vô số chỗ sau, và những chỗ thêm sau chính là những chỗ không ai nhớ bảo vệ.
  Hai lớp: **giá trị thật** (mọi secret process đang giữ) + **hình dạng** (`sk-…`, `AIza…`,
  `Bearer …`, password trong DSN) cho key mình không giữ. **Và ngay sau đó lộ thêm một chỗ nữa**:
  `list_models` log exception thô — quên `redact()`. Bài học: mỗi `log.warning` mang exception
  của SDK là một đường rò mới.

  **Biến môi trường đè `.env` — mất một buổi debug.** User test key bằng PowerShell → 200; app
  gửi đi → 401. Cả hai key **dài đúng 164 ký tự, cùng prefix `sk-proj-`**, nên không có gì trông
  sai. Nguyên nhân: pydantic-settings **ưu tiên biến môi trường hơn `.env`**, và máy còn một
  `OPENAI_API_KEY` cũ. Triệu chứng *y hệt* key hỏng, nên mọi bước tiếp theo (chép lại key, kiểm
  tra dấu nháy, đếm độ dài) đều đi soi đúng cái file **không được đọc**. Cách tìm ra: **hash hai
  giá trị rồi so** — không in ra. Giờ `llm providers` và trang `/models` cảnh báo thẳng
  (`redact.shadowed_secrets`).

  **"Credit còn lại" không lấy được từ provider** — đã thử: Anthropic `cost_report` và OpenAI
  `organization/costs` đều đòi **Admin key**, trả 401 với key thường. Nên `llm.budget_usd` là số
  **user tự nhập**, còn "đã dùng" là phần **JobPilot tự đo**; "còn lại" là hiệu hai số đó và UI
  nói rõ **đây là bộ đếm ngân sách, không phải số dư tài khoản**. Không bịa ra một con số trông
  như số dư — đúng luật "sai dữ liệu *trông như đúng* tệ hơn thiếu dữ liệu".

  **Ba bug kiểu "báo cáo thành công nhưng sai", cả ba chỉ lộ khi chạy thật:**
  1. `thinking={"type":"adaptive"}` áp cho mọi model ⇒ Haiku trả 400 *"adaptive thinking is not
     supported on this model"*. Không phải chuyện tốn token — nó **chặn luôn cả tầng model rẻ**,
     tức chặn đúng luật 3. Sửa: registry tắt thinking cho `classify`, và client **tự tắt rồi gọi
     lại một lần** khi gặp đúng lỗi đó — không hardcode danh sách model (danh sách sai ngay tuần
     có model mới).
  2. `models.list()` của Gemini **có** `gemini-2.5-flash`, nhưng `generateContent` trả **404
     "no longer available to new users"**. Danh sách là *menu*, không phải lời hứa.
  3. So id model bằng `==` đánh dấu `claude-haiku-4-5` là "không khả dụng" vì Anthropic liệt kê
     bản có ngày `claude-haiku-4-5-20251001`. Phải so **theo prefix** — và cái bị đánh dấu sai
     lại đúng là model rẻ đạt 5/5, tức bug chỉ đường **tránh xa** câu trả lời mà trang này sinh
     ra để tìm.

  **Một bug do nuốt lỗi, lần thứ hai trong hai phase.** `list_models` trả `[]` cho Gemini; thêm
  log mới thấy *"Cannot send a request, as the client has been closed"* — `genai.Client(...)` viết
  inline trong comprehension bị GC giữa chừng vì pager là lazy. Đọc như lỗi auth mà không phải.

  **Hai test tự phơi mình ra khi config đổi:**
  `test_the_shipped_config_is_what_it_claims_to_be` đọc `get_config()` (đã merge
  `config.local.yaml`) nên đỏ ngay khi user đổi backend — **đúng cái bẫy máy-phụ-thuộc mà Phase
  20 đã sửa một lần**; giờ đọc thẳng `config.yaml`. Và test chống-leak viết theo *snapshot* danh
  sách field thì vỡ mỗi lần thêm tính năng ⇒ đổi thành **luật**: tên giống secret **và** kiểu
  string. Viết luật cũng phải cẩn thận: bản đầu bắt nhầm `has_key` (bool) và `input_tokens` (int) —
  một check hay kêu oan là một check bị người ta tắt.

  **Verify:** 642 test, ruff + `tsc` sạch; trang `/models` chụp thật ở **light + dark**, console
  sạch; đổi provider+model bằng chuột → ghi `config.local.yaml` → `llm bench` chạy đúng backend
  mới. Lưu ý khi verify web: **API chạy bằng uvicorn không `--reload` sẽ giữ code cũ** — hai
  "bug" đầu tiên nhìn thấy trên trang hoá ra chỉ là server chưa restart.

- ✅ **Phase 20c (tiếp)** — Sau khi user gỡ biến môi trường `OPENAI_API_KEY` cũ: `.env` được đọc
  đúng (fingerprint khớp), `shadowed_secrets()` rỗng, cảnh báo biến mất khỏi `llm providers` và
  trang `/models`. **OpenAI chạy thật cho cả hai schema** — `MailVerdict` 5/5 và `TailorPlan`
  **1/1 qua guardrail vòng đầu** dưới strict mode. Tức cả ba provider giờ đã verify trên cả
  schema phẳng lẫn schema lồng; không còn đường nào "chưa bao giờ gọi thật".

  **Và bộ đo lập tức bác bỏ kết luận trước đó của chính mình.** Ở **n=5**, `gemini-3.1-flash-lite`
  là rẻ nhất *và* nhanh nhất (p50 **705ms**). Lên **n=10**: p50 thành **2732ms**, còn `gpt-4o-mini`
  1101ms với giá thấp hơn ⇒ **đảo ngược cả hai tiêu chí**. Đã đổi `classify` sang
  `openai/gpt-4o-mini`. Đây chính xác là thứ `MIN_SAMPLE` được viết ra để ngăn — và nó ngăn được
  người viết ra nó, vì tôi đã đọc con số `n=5` như thể nó là một tỉ lệ. **Luật rút ra: khi cột tỉ
  lệ còn hiện `n=<count>` thì chưa được chốt model.**

  `tailor` trên `gpt-4.1`: 1/1 vòng đầu, ~$0.016 và ~9s so với `claude-opus-4-8` ~$0.10 và ~39s.
  **Chưa đổi** — guardrail chỉ chứng minh *không bịa*, không chứng minh xếp hạng tốt; và n=1 thì
  không phải bằng chứng. Muốn đổi thì phải đọc bản CV thật ở trang CV Review.

  **Review gate (2 subagent, cả hai chạy trên diff thật):** `phase-reviewer` → APPROVE kèm 2
  "nên sửa"; một agent **security review** riêng → 3 finding. Hai bên **độc lập tìm ra cùng một
  lỗ** (`PUT /settings` ghi được secret xuống `config.local.yaml`), điều đó làm nó đáng tin hơn
  hẳn một report đơn lẻ. Đã sửa cả ba trước khi push:
  1. **Traceback rò key** (`orchestrator.py:225`) — nặng nhất, và tinh vi nhất. `LlmError` scrub
     *message* của chính nó, nhưng nó được `raise ... from exc`, và **exception gốc của SDK vẫn
     trích nguyên key**. `str(exc)` sạch, `traceback.format_exc()` thì **không** — mà task hỏng
     nào cũng log cái thứ hai. Bài học tổng quát: scrub theo *chuỗi nguyên nhân*, không chỉ theo
     một object; bất kỳ chỗ nào render traceback là một sink mới.
  2. **`PUT /settings` ghi secret ra `config.local.yaml`** — Pydantic *bỏ qua* field lạ chứ không
     từ chối, nên validate vẫn pass trong khi overlay được ghi từ **dict thô**. Sửa bằng
     `config.prune_to_schema()` đặt **trước** bước merge, và áp cho **mọi** section (`app`,
     `crawl`, `apply`, `cv` cùng dính lỗ này, không riêng `llm`).
  3. **`_offered()` prefix quá lỏng** — `gemini-3.5-flash-lite` "bảo lãnh" cho
     `gemini-3.5-flash`, khiến một model đã bị withdraw hiện ra là dùng được. Prefix chỉ hợp lệ
     khi phần đuôi là **8 chữ số** (date snapshot của Anthropic). Date = cùng model; `-lite` =
     model khác.
  Thêm `ya29.` vào `_SHAPES` (chưa dùng tới, nhưng rẻ), và bỏ `BenchResult.latency_ms` +
  `median_latency_ms` — dead code chưa bao giờ được ghi. 645 test.

- ✅ **Phase 21** — Trang **/market**: nghiên cứu thị trường từ corpus đã crawl. `crawler/salary.py`
  + `crawler/skills.py` + `vietnam.canonical_city` (Phase A: trích dữ liệu), `analytics/market.py`
  + `GET /analytics/market` + `web/src/pages/Market.tsx` (Phase B: đo và vẽ).

  **Đếm dữ liệu trước khi thiết kế, và nó đổi hẳn thứ tự công việc.** Yêu cầu là "nhiều biểu đồ
  thống kê + nghiên cứu thị trường". Đếm thật: `applications` **0**, `application_events` **0**
  ⇒ mọi funnel sau khi nộp trống; `salary` **3/73** mà **2 là bug scraper**; `skills` 24/73 và
  LinkedIn (**57% corpus**) không có tag nào. Vẽ 12 biểu đồ lúc đó = một trang đầy panel trống
  và sai. Nên: **làm dữ liệu trước, biểu đồ sau**.

  **Luật của phase này: mỗi facet tự khai mẫu số.** `Facet.covered/total`, hiện ra UI là
  "18 of 73 jobs" chứ không phải một %. Lý do rất cụ thể: một bảng xếp hạng skill dựng từ 18/73
  job là *sự thật về 18 job* và *hư cấu về thị trường* — chỉ mẫu số phân biệt được hai thứ đó.
  Cùng họ với `MIN_SAMPLE` của `llm/stats.py`, áp cho một kiểu "mỏng" khác.

  **Ba lỗi "trông như đúng", cả ba chỉ thấy khi nhìn biểu đồ thật:**
  1. **Skill**: `+2` (badge tràn của card ITviec), `Vollzeit`, `Backend Developer`,
     `IT Services and IT Consulting`, `India` đứng ngang `Java`. Lọc bằng **pattern**, không
     bằng blocklist: `_ROLE_RE` khớp **danh từ số ít** nên bỏ "software engineer" mà vẫn giữ
     "data engineering" — phân biệt đó chính là lý do nó là regex.
  2. **City**: `Hà Nội` / `Ha Noi` / `Hanoi` ra **ba cột**, mỗi cột 1/3 số thật (4+4+3 → 11).
     `canonical_city` fold ASCII rồi map alias — cùng kỹ thuật `apply/inbox.fold` đã dùng để so
     tên công ty với domain.
  3. **Lương**: `"15tr - 25tr"` ra **15–15**. Unit nằm giữa số và dấu gạch làm vỡ regex range,
     rơi xuống nhánh một-số, trần bị giảm một nửa **không báo gì**.

  **Hai lỗi biểu đồ, phát hiện bằng cách nhìn ảnh chụp chứ không phải bằng test:**
  - Tô 8 màu categorical xuống 15 dòng skill = tô theo **thứ hạng**. Màu phải theo *thực thể*;
    đổi filter là đổi màu, tức là mã hoá một thứ không tồn tại. Một measure ⇒ một màu.
  - `SOURCE_ORDER` có 10 mục nhưng palette có 8 hue ⇒ `lever` (index 8) đội đúng màu xanh của
    `itviec`. Hai board cùng màu **tệ hơn** một board lạ không có màu riêng, vì nó trông như cố ý.

  **Không đoán khi thiếu ký hiệu**: `"20 - 60"` không có currency ⇒ `None` (là triệu VND hay
  USD/giờ tuỳ board — đoán là tung đồng xu rồi trình bày như sự thật). `"Up to 3000"` ⇒
  `min=None`, không bịa 0 (một midpoint tưởng tượng sẽ kéo tụt median cả corpus). Quy đổi USD
  dùng `USD_VND_RATE` kèm `FX_CHECKED_ON`, UI gọi nó là **ước tính** — cùng họ với bảng giá
  `llm/pricing.py`, và nó **sẽ** cũ đi.

  **Sidebar**: `Layout.tsx` **đã có** một sidebar (8 mục). Không thêm cái thứ hai ở tầng Layout —
  sẽ đổi bố cục mọi trang để phục vụ một trang. Section-nav nằm **trong** `Market.tsx`.

  **Verify:** 658 test; `backfill --force` chạy trên **73 job thật** rồi *đọc tay* output (banner
  ITviec → `None`, lương thật → số đúng, city gộp đúng); `/market` chụp thật **light + dark**,
  console sạch. `--force` tồn tại vì một bản vá *parser* phải chạy lại được trên chính những row
  mà nó từng trả lời sai — không có nó thì bug bị đóng băng vào dữ liệu nó làm hỏng.

---

## CV Studio — preview đọc được, và LaTeX sửa được (theo yêu cầu, không phải phase đánh số)

**Ba lời phàn nàn về khung preview, sửa theo đúng thứ tự nó làm phiền.**

- **Mảng đen dưới trang.** Khung ghim `h-[780px]`, mà trang A4 fit theo bề rộng rail 378px chỉ
  cao ~535px ⇒ 245px còn lại là **nền của chính PDF viewer**. Không lấy tỉ lệ A4 trần được: đo
  thật thì viewer chèn ~4px mỗi bên, ~3px trên, và fit trang vào phần *bên trong* padding đó —
  dùng 210/297 thẳng là luôn **ước lượng thừa**. Nay ước lượng **hụt 2px có chủ ý** rồi clip
  phần dư: sai thì mất 2px của lề 1.5cm, không phải hiện một vệt đen.
- **Không đọc nổi.** Rail 378px, CV là một tài liệu. Thêm chế độ toàn màn hình + link mở tab mới.
  Overlay **portal ra `<body>`**: để nguyên tại chỗ thì nó nằm trong subtree `sticky` của rail,
  và header dính của app vẽ đè lên — nút Close **bấm không được**. Không nhìn ảnh nào ra;
  Playwright báo thẳng `<header …> intercepts pointer events`. Đây là lý do drive UI thật khác
  với chụp ảnh UI.
- **Trống trơn tới khi bấm Compile**, dù PDF đã nằm sẵn trên đĩa. Giờ fetch ngay lúc mount.

**Một bug tự lộ ra khi đang sửa:** object URL bị `revokeObjectURL` trong **cleanup** của effect —
tức đúng lúc compile *bắt đầu*. Suốt ~10–30s Docker build, khung trỏ vào blob đã huỷ. Giờ chỉ
revoke bản cũ **sau khi** bản mới về. Bài học cũ dạng mới: dọn dẹp theo vòng đời của *effect*
trong khi thứ được dọn có vòng đời của *màn hình*.

**Raw LaTeX (user chọn phương án "lưu override vào version").**

- JSON **vẫn** là nguồn sự thật cho CV *nói gì*; override chỉ đè lên cách nó *serialize* — đúng
  những thứ editor không có field: `\vspace` kéo dòng mồ côi về trang 1, macro Awesome-CV mà
  schema không mô hình hoá. Lưu ở `cv_versions.meta.tex_override` ⇒ **không cần migration**, và
  mỗi version ghi lại đúng thứ đã build.
- **Đánh đổi một chiều, và UI phải nói ra**: không có gì parse `.tex` ngược về JSON, nên khi
  override còn hiệu lực thì các field **không tới được PDF**. Banner trong tab + dòng dưới tiêu đề
  trang + một cú bấm để revert. Override ghi **đè lên** project đã render, nên sửa `cv.tex` thì
  các file section vẫn bám theo JSON.
- **Hai thứ cố tình KHÔNG làm**: (1) lưu document **không** xoá override — mất `.tex` viết tay chỉ
  vì sửa số điện thoại là không thể bào chữa; xoá có động từ riêng (`DELETE`), và `PUT` với
  `files: {}` trả **422** chứ không lặng lẽ thành delete. (2) **rollback mang override về theo**,
  vì "khôi phục v7" phải nghĩa là *bản PDF mà v7 đã tạo ra* — lấy document mà bỏ `.tex` nó compile
  từ đó là khôi phục một version chưa từng tồn tại.
- Path trong override được validate **trước khi** thành path dưới `out/cv/<scope>/`: tương đối,
  không traversal, không backslash, chỉ `.tex`. Backslash phải chặn riêng: `PurePosixPath` đọc
  `a\b.tex` là **một** segment vô hại, còn Windows thì không.
- Editor là gutter + textarea có bắt phím Tab, **không** Monaco — ~5 MB dependency để tô màu cú
  pháp cho một file hiếm khi mở.

**Verify:** 677 test; `tsc` sạch; chạy thật đầu-cuối trên browser headed + API + Postgres + Docker
LaTeX: sửa `resume/summary.tex` chèn marker → Save → Compile → **đọc lại PDF bằng pypdf thấy
marker** → Revert → Compile → marker biến mất. Cửa sổ read-only lúc save verify bằng cách **giữ
request mở** (route delay), không phải bằng cách đua với nó. Ảnh light + dark.

**Reviewer bắt 4 lỗi, sửa hết trước khi push**: textarea vẫn gõ được trong lúc save (refetch sau đó
ghi đè thứ vừa gõ), `PUT {"files": {}}` ngầm thành `DELETE`, `onClose` inline dựng lại effect phím
Esc mỗi lần parent render, và rollback làm rơi override.

**Ghi chú môi trường:** headless Chrome không có PDF viewer ⇒ mọi kiểm tra preview phải chạy
`headless=False`. Lỗi console duy nhất còn lại là `chrome-extension://…/pdf_embedder.css` — asset
của chính PDF viewer trong Chrome, không phải của app.
