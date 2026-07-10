# JobPilot Web Dashboard

Local control plane for JobPilot (PLAN.md §5.6) — React + Vite + TypeScript +
TailwindCSS. **Phase 4 MVP**: Dashboard (KPI + approach funnel + charts), Jobs
(filter/search + shortlist/skip), Job detail, realtime via WebSocket.

Later phases add CV Studio · CV Review · Applications (Kanban) · Settings · Runs.

## Run

```bash
cp .env.example .env.local   # set VITE_API_TOKEN to match the backend .env
npm install
npm run dev                  # http://127.0.0.1:5173
```

Needs the backend running: `python -m jobpilot.cli serve` (http://127.0.0.1:8000).

## Design

"Flight deck" — warm-neutral surfaces, a marigold accent (runway light), aqua
LIVE indicator. Charts use the validated `dataviz` palette (categorical hues by
source, ordinal blue for the funnel). Display face Space Grotesk; JetBrains Mono
for job IDs and metrics. Dark mode is a selected palette, not an auto-flip.

## Layout

```
src/
  App.tsx            routes + realtime version nudge
  components/
    ui.tsx           Card/Button/Badge/Input/Select/Skeleton (shadcn-style)
    Layout.tsx       sidebar + LIVE indicator + theme toggle
    ApproachFunnel   signature: pipeline as an aircraft approach
    StatusPill / MatchMeter / FreshBeacon / StatCard
    charts/          BySourceChart, ByDayChart, palette (dataviz)
  pages/             Dashboard, Jobs, JobDetail
  hooks/             useApi, useWebSocket
  lib/               api, format, theme, utils
```
