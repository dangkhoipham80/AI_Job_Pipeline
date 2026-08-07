# 🤖 JobPilot — CV autopilot, on your own machine

> Crawl developer jobs → review them on a local dashboard → tailor your CV to one → approve the diff → apply.
> Built on the [Awesome-CV](https://github.com/posquit0/Awesome-CV) LaTeX template, which is also usable on its own.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![Postgres](https://img.shields.io/badge/PostgreSQL-17-blue?logo=postgresql)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-LaTeX%20build-blue?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repo has two layers:

1. **CV template** — the Awesome-CV LaTeX scaffolding (`awesome-cv.cls`, `fontawesome.sty`, `fonts/`),
   built in Docker. Useful by itself; see [Just the CV builder](#-just-the-cv-builder).
2. **JobPilot** — a FastAPI + React + PostgreSQL pipeline that crawls jobs, tailors your CV per job
   with Claude, and dispatches applications. Architecture in [`PLAN.md`](PLAN.md), CV-tailoring rules
   in [`SKILL.md`](SKILL.md), contributor guide in [`CLAUDE.md`](CLAUDE.md).

> **No CV lives in this repo.** Your name, email, history and every tailored version live in the
> `cv_versions` table of your local Postgres. A fresh database seeds an *empty* CV that you fill in
> through the CV Studio. `jobpilot/cv/sample.py` is fictional data used only by tests.

---

## 🧭 What it does

```
crawl sources ──▶ Jobs dashboard ──▶ you shortlist ──▶ Claude tailors the CV
                                                             │
                          you approve / edit the diff ◀───────┘
                                     │
                    email (full-auto, 3 safety gates) │ portal & external (you press submit)
```

Three rules the code is built around:

- **No invented experience.** The tailor agent may only reorder, drop or rephrase things already in
  your CV — the plan schema is index-based, so "add a skill you don't have" is not expressible.
- **You approve anything that leaves the machine**, except the email channel once you explicitly
  enable it (and it stays dry-run until you turn that off too).
- **robots.txt and rate limits are respected.** A source that disallows automated access is not
  crawled — see [Sources](#-sources).

---

## 🚀 Quick start

```bash
# 1. install (extras are opt-in; `all` gets everything)
pip install -e '.[all]'
playwright install chromium          # only needed for ITviec / VietnamWorks

# 2. point at a database and set a local API token
cp .env.example .env                 # then edit DATABASE_URL + JOBPILOT_API_TOKEN
psql -U postgres -c "CREATE DATABASE jobpilot;"
alembic upgrade head

# 3. run it
uvicorn jobpilot.api.main:app --reload    # API + WebSocket on :8000
cd web && npm install && npm run dev      # dashboard on :5173
```

Or `make dev` to start the lot.

Everything binds to `localhost` and is guarded by a token from `.env` — this is a single-user local
tool, not a service to expose.

### Day-to-day CLI

```bash
python -m jobpilot.cli crawl                          # crawl every enabled source
python -m jobpilot.cli crawl --query "java spring boot" --limit 30
python -m jobpilot.cli run --every 60                 # simple loop for cron
python -m jobpilot.cli cv import my-cv.local.json     # load a CV into the DB
python -m jobpilot.cli cv build                       # render JSON → .tex → PDF
python -m jobpilot.cli tailor <job_id>                # needs ANTHROPIC_API_KEY
python -m jobpilot.cli apply <job_id>
pytest jobpilot/tests
```

Keep the query short. It becomes a search term at each site, and an over-specific one
("Java Spring Boot Backend") can legitimately match nothing.

---

## 🔎 Sources

Configured in `jobpilot/config.yaml`, toggled on the Settings page. Adding one is a scraper plus a
line of config (`PLAN.md` §5.1.1).

| Source | Tier | How it's read | Notes |
|---|---|---|---|
| **ITviec** | 1 | Playwright | Cloudflare-protected; salaries are behind a login, so `salary` is `null` |
| **TopCV** | 1 | Playwright | Server-rendered + schema.org `JobPosting`. Keyword goes in the *path*, not `?keyword=` |
| **VietnamWorks** | 1 | Playwright | Jobs arrive by XHR; lazy-loads ~9–20 cards per page, so it is paged |
| **LinkedIn** | 1 | IMAP | Reads **Job Alert emails in your own inbox**. LinkedIn is never crawled |
| **We Work Remotely** | 2 | RSS | One feed per category, full JD inline, no browser needed |
| **Arbeitnow** | 2 | JSON API | Really paginated; mostly Germany/EU, descriptions often in German |
| **Greenhouse** | 3 | Board JSON API | Any company on Greenhouse. Off by default — list the boards you follow |
| **Lever** | 3 | Board JSON API | Any company on Lever. Off by default |
| TopDev, Ashby | — | — | Not implemented (see below) |

Tier-2 sources are remote/worldwide roles. Turn them off in Settings if you only want Vietnam.

**Tier 3 — company career pages.** Most companies don't build a job board, they rent one, and a role
usually appears there before it reaches any aggregator. One adapter reaches every company on a
platform, so following a new company is one word in `config.yaml` — no code:

```yaml
ats:
  greenhouse: [gitlab, grafanalabs, elastic]   # the slug in job-boards.greenhouse.io/<slug>
  lever:      [palantir, spotify]              # the slug in jobs.lever.co/<slug>
```

Then enable `greenhouse` / `lever` in Settings. Each board is one request per crawl, so a long list
is a slow crawl.

**Sources deliberately not added.** Four remote-job feeds were evaluated for tier 2 and rejected —
read `CLAUDE.md` → *"Nguồn tier-2 đã loại"* before adding one, so the checks aren't repeated:

- **Remotive**, **Jobicy** — `robots.txt` disallows `/api/`, which is the only useful endpoint.
- **RemoteOK**, **TopDev** — `Content-Signal: ai-train=no, use=reference` plus a `ClaudeBot` block.
  Not obviously fatal, but it needs a deliberate decision rather than a default.
- **Himalayas** — robots is fine, but the API ignores every filter parameter and silently caps
  `limit` at 20, so a crawl would "succeed" and hand back jobs for other professions.

> Read the **whole** `robots.txt` before writing a scraper. Jobicy's `Disallow: /api/` is on line 48;
> a `head -40` made it look permissive, and only a live run against `RobotsPolicy` caught it.

---

## 📄 Just the CV builder

The LaTeX scaffolding works standalone — put a `cv.tex` next to `awesome-cv.cls` and run:

```bash
# Linux / macOS / WSL
docker run -u $UID:$GID --rm -v "$PWD:/work" csmith/awesome-cv-builder
# Windows PowerShell
docker run --rm -v ${PWD}:/work csmith/awesome-cv-builder
```

Output is `cv.pdf` in the same directory. JobPilot uses this exact image, writing tailored builds to
`out/cv/<scope>/` and never touching your master.

Prefer editing through the **CV Studio** rather than by hand: content is structured JSON that is
serialized to `.tex` via Jinja2, so hand-edited `.tex` loses the round trip. Change the accent colour
with `theme.color` in the Studio, not in the `.cls`.

**Troubleshooting.** On Windows, give Docker Desktop access to the drive under
Settings → Resources → File Sharing. On Linux/macOS the `-u $UID:$GID` flag keeps output files owned
by you. Install the `[cv]` extra for `pypdf`, or the page count reads as unknown.

---

## 🗺️ Project layout

```
jobpilot/
  api/        FastAPI: REST + WebSocket, one route module per surface
  crawler/    base.py (contract + paging loop) · one module per source · feed.py for RSS/JSON
  cv/         CvDocument schema · Jinja2 → .tex · Docker compile · version store
  tailor/     index-based plan schema · anti-fabrication guard · Claude engine · diff
  apply/      cover letter · email (3 gates) · portal hand-off · dispatcher
  store/      SQLAlchemy models + Alembic migrations
  slack/      optional secondary channel; a pure client of the REST API
web/          React + Vite + TS + Tailwind dashboard
```

## 🤝 Contributing

Read [`CLAUDE.md`](CLAUDE.md) first — it holds the conventions and, more usefully, the list of bugs
that only appeared against live sites, each with the test that now pins it.

## 📝 License

MIT — see [LICENSE](LICENSE).

## ⭐ Acknowledgments

- [Awesome-CV](https://github.com/posquit0/Awesome-CV) by Claud D. Park
- [csmith/awesome-cv-builder](https://hub.docker.com/r/csmith/awesome-cv-builder) Docker image
- Job data from [We Work Remotely](https://weworkremotely.com/) and
  [Arbeitnow](https://www.arbeitnow.com/) via their public feeds
