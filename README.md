# 🤖 JobPilot — CV autopilot, on your own machine

> Crawl developer jobs → review them on a local dashboard → tailor your CV to one → approve the diff → apply → track what comes back.
> Built on the [Awesome-CV](https://github.com/posquit0/Awesome-CV) LaTeX template, which is also usable on its own.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![Postgres](https://img.shields.io/badge/PostgreSQL-17-blue?logo=postgresql)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-LaTeX%20build-blue?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repo has two layers:

1. **CV template** — the Awesome-CV LaTeX scaffolding (`awesome-cv.cls`, `fontawesome.sty`, `fonts/`),
   built in Docker. Useful by itself; see [Just the CV builder](#-just-the-cv-builder).
2. **JobPilot** — a FastAPI + React + PostgreSQL pipeline that crawls jobs, tailors your CV per job
   with an LLM, dispatches applications and tracks what came back. Architecture in
   [`PLAN.md`](PLAN.md), CV-tailoring rules in [`SKILL.md`](SKILL.md), contributor guide in
   [`CLAUDE.md`](CLAUDE.md).

> **No CV lives in this repo.** Your name, email, history and every tailored version live in the
> `cv_versions` table of your local Postgres. A fresh database seeds an *empty* CV that you fill in
> through the CV Studio. `jobpilot/cv/sample.py` is fictional data used only by tests.

---

## 🧭 What it does

```
crawl sources ──▶ Jobs dashboard ──▶ you shortlist ──▶ a model tailors the CV
                                                              │
                           you approve / edit the diff ◀───────┘
                                      │
                     email (full-auto, 3 safety gates) │ portal & external (you press submit)
                                      │
                                      ▼
              replied · interview · offer · rejected ◀── your inbox suggests, you confirm
```

Three rules the code is built around:

- **No invented experience.** The tailor agent may only reorder, drop or rephrase things already in
  your CV — the plan schema is index-based, so "add a skill you don't have" is not expressible.
- **You approve anything that leaves the machine**, except the email channel once you explicitly
  enable it (and it stays dry-run until you turn that off too).
- **robots.txt and rate limits are respected.** A source that disallows automated access is not
  crawled — see [Sources](#-sources).

### The dashboard

Nine pages, all at `localhost:5173`:

| Page | What it's for |
|---|---|
| **Deck** | The funnel and the day's numbers |
| **Jobs** | Everything crawled, filterable; shortlist or skip from the row |
| **CV Studio** | Structured editor for the Master CV, version history, diff any two versions |
| **Applications** | Board of what was dispatched, per stage; follow-up reminders and inbox suggestions |
| **Runs** | Start a crawl, watch the queue, read the run history |
| **Market** | What the crawled corpus looks like — skills, pay, cities, seniority |
| **Models** | Pick a provider and model per task; cost, latency and first-try rate per backend |
| **Settings** | Sources, crawl scope, apply gates — written to a gitignored overlay |
| **Guide** | How the pipeline fits together |

Lists are paginated server-side with a page size you pick per list (10/25/50/100), remembered
between visits.

---

## 🚀 Quick start

```bash
# 1. install (extras are opt-in; `all` gets everything)
pip install -e '.[all]'
playwright install chromium          # only needed for ITviec / VietnamWorks

# 2. point at a database and set a local API token
cp .env.example .env                 # DATABASE_URL + JOBPILOT_API_TOKEN, plus a key for
                                     # whichever provider you pick (see Models)
psql -U postgres -c "CREATE DATABASE jobpilot;"
alembic upgrade head

# 3. run it
uvicorn jobpilot.api.main:app --reload    # API + WebSocket on :8000
cd web && npm install && npm run dev      # dashboard on :5173
```

`make dev` brings up Postgres and the API; the dashboard needs its own terminal (`make web`), since
`uvicorn --reload` blocks and a Makefile runs its prerequisites in sequence.

Everything binds to `localhost` and is guarded by a token from `.env` — this is a single-user local
tool, not a service to expose.

### Day-to-day CLI

```bash
python -m jobpilot.cli crawl                          # crawl every enabled source
python -m jobpilot.cli crawl --query "java spring" --limit 30
python -m jobpilot.cli run --every 60                 # simple loop for cron
python -m jobpilot.cli backfill --force               # re-derive facets after fixing a parser
python -m jobpilot.cli cv seed                        # empty Master CV, if there isn't one
python -m jobpilot.cli cv import my-cv.local.json     # load a CV into the DB
python -m jobpilot.cli cv export my-cv.local.json     # back it up (gitignored)
python -m jobpilot.cli cv build                       # render JSON → .tex → PDF
python -m jobpilot.cli tailor <job_id>                # needs a key for the configured provider
python -m jobpilot.cli apply <job_id>
python -m jobpilot.cli confirm-submit <job_id>        # you submitted a portal/external one by hand
python -m jobpilot.cli llm providers                  # what runs what, which keys are missing
python -m jobpilot.cli llm stats                      # cost, first-try rate, latency per backend
python -m jobpilot.cli llm bench --task classify      # score a backend on known answers
pytest jobpilot/tests                                 # 690 tests
```

Keep the query short. It becomes a search term at each site, and an over-specific one
("Java Spring Boot Backend") can legitimately match nothing.

---

## 🧠 Models

Nothing is hard-wired to one vendor. Provider and model are chosen **per task** —
`tailor`, `letter`, `classify` — in `jobpilot/config.yaml` or from the **Models** page, which writes
to the gitignored overlay:

```yaml
llm:
  provider: claude          # default for anything not set below
  tailor: ""                # "" = use `provider`
  letter: ""
  classify: ""              # e.g. openai — the cheap, easy call
  models:
    claude: claude-opus-4-8
    openai: gpt-4.1
    gemini: gemini-3.5-flash
```

Adding a backend is one entry in `llm/registry.PROVIDERS` plus a client module — not a `Literal`
edited in four places. The three providers do not accept the same JSON Schema, so `llm/schema.py`
adapts it (Gemini's subset, OpenAI's strict mode).

**Measure, don't guess.** Every call — including ones the anti-fabrication guard rejects, and ones
that error — writes a row to `llm_calls`. Read it with `jobpilot llm stats` or the Models page:
cost, latency, and how often a plan cleared the guard first try. `jobpilot llm bench` re-runs a
fixed scoring set so "cheapest that still works" is a result rather than a hunch. Small samples show
`n=<count>` instead of a percentage — at n=5 this benchmark once ranked a model fastest that turned
out to be slowest at n=10.

Two honest limits:

- **Only one privacy warning matters: Gemini's free tier.** Paid Anthropic, OpenAI and Gemini do not
  train on API input. Unpaid Gemini does, and its terms say not to send personal information — which
  is exactly what `tailor` and `letter` send, since the whole Master CV goes in the system prompt.
  Set `llm.gemini_paid_tier: false` and JobPilot warns before every such call. It warns; it does not
  block.
- **"Credit remaining" is a budget counter, not an account balance.** Anthropic, OpenAI and Google
  all require an admin key for their cost endpoints, so the figure is your own `llm.budget_usd` minus
  what JobPilot measured. Models with no entry in `llm/pricing.py` count as unpriced rather than
  free, and every total says how many.

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
| TopDev, Ashby | — | — | Deliberately absent — see below |

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

**Sources deliberately not added.** Several were evaluated and rejected — read `CLAUDE.md` →
*"Nguồn tier-2 đã loại"* before adding one, so the checks aren't repeated:

- **Remotive**, **Jobicy** — `robots.txt` disallows `/api/`, which is the only useful endpoint.
- **RemoteOK**, **TopDev** — `Content-Signal: ai-train=no, use=reference` plus a `ClaudeBot` block.
  Not obviously fatal, but it needs a deliberate decision rather than a default.
- **Ashby** — `api.ashbyhq.com` serves no `robots.txt` at all (401) while `jobs.ashbyhq.com`
  disallows `/api/`. Absent robots is not permission.
- **Himalayas** — robots is fine, but the API ignores every filter parameter and silently caps
  `limit` at 20, so a crawl would "succeed" and hand back jobs for other professions.

An API that returns 200 while ignoring your filter is more dangerous than one that returns an
error. If the response echoes something like `appliedFilters`, check it.

> Read the **whole** `robots.txt` before writing a scraper. Jobicy's `Disallow: /api/` is on line 48;
> a `head -40` made it look permissive, and only a live run against `RobotsPolicy` caught it.

---

## 📬 After you apply

Applying is the middle of the story, not the end.

- **Follow-ups.** Applications that have gone quiet surface on the board with a suggested nudge.
  Nothing is sent — a follow-up is a message to a person deciding about you, and the same rule that
  gates apply gates this.
- **Outcomes.** Record `replied`, `interview`, `offer`, `rejected`, `withdrawn` or `ghosted` per
  application, with history. The last two are yours to declare — no counter decides you were
  ghosted. Rates are computed from what an application *ever reached*, not from where it sits now,
  or interview rate would fall when interviews turn into offers.
- **Inbox sync** (off by default). With IMAP credentials set, JobPilot reads *your* mailbox, matches
  messages to applications locally, and only then asks a model what a matched reply means. Mail that
  belongs to no application never leaves the machine. Every suggestion quotes the line it read, and
  nothing is recorded until you press the button.

Enable it under `apply.inbox` with `IMAP_USER` / `IMAP_PASSWORD` — for Gmail that must be an
[App Password](https://myaccount.google.com/apppasswords), not your account password.

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
  api/        FastAPI: REST + WebSocket, one route module per surface · paging.py
  crawler/    base.py (contract + paging loop) · one module per source · feed.py for RSS/JSON
  cv/         CvDocument schema · Jinja2 → .tex · Docker compile · version store · ats.py
  tailor/     index-based plan schema · anti-fabrication guard · model engine · diff
  apply/      cover letter · email (3 gates) · portal hand-off · dispatcher
              followup.py (reminders) · outcome.py (what happened) · inbox.py (read replies)
  llm/        provider registry · per-task engines · schema adapters · cost & quality telemetry
  analytics/  market facets, each carrying how much of the corpus it actually saw
  store/      SQLAlchemy models + Alembic migrations
  slack/      optional secondary channel; a pure client of the REST API
  orchestrator.py   task queue behind the 202-and-a-task-id endpoints
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
