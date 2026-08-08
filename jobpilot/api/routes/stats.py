"""Dashboard stats: funnel by status + counts by source/level/day + fresh flag."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot import llm
from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import (
    LlmStatsOut,
    ModelOptionOut,
    OutcomeStats,
    ProviderSpendOut,
    StatsOut,
)
from jobpilot.apply.outcome import outcome_counts
from jobpilot.config import get_config
from jobpilot.llm.stats import MIN_SAMPLE, backend_stats
from jobpilot.store.models import Job, JobStatus
from jobpilot.timeutil import vn_now

router = APIRouter(tags=["stats"], dependencies=[Depends(require_token)])


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    status_rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    source_rows = db.execute(select(Job.source, func.count()).group_by(Job.source)).all()
    level_rows = db.execute(select(Job.level, func.count()).group_by(Job.level)).all()
    day_rows = db.execute(
        select(func.date(Job.crawled_at), func.count()).group_by(func.date(Job.crawled_at))
    ).all()

    # Seed every status at 0 so the funnel always renders all stages.
    by_status = {s.value: 0 for s in JobStatus}
    for st, n in status_rows:
        key = st.value if isinstance(st, JobStatus) else str(st)
        by_status[key] = n

    by_source = {src: n for src, n in source_rows}
    by_level = {(lvl or "unknown"): n for lvl, n in level_rows}
    by_day = {str(day): n for day, n in day_rows if day is not None}

    cutoff = vn_now() - timedelta(hours=get_config().crawl.fresh_hours)
    fresh = db.scalar(select(func.count()).where(Job.posted_at >= cutoff)) or 0

    total = sum(by_source.values())
    return StatsOut(
        total=total,
        fresh=fresh,
        by_status=by_status,
        by_source=by_source,
        by_level=by_level,
        by_day=by_day,
        # Counted from the event log, not from the funnel: `by_status` stops at
        # SUBMITTED by design, and everything worth knowing about a job search
        # happens after that (Phase 18).
        outcomes=OutcomeStats(**outcome_counts(db)),
    )


#: A provider's dated snapshot suffix — ``claude-haiku-4-5-20251001``.
_DATE_SUFFIX = re.compile(r"^\d{8}$")


def _offered(model: str, live: list[str] | None) -> bool:
    """Whether ``model`` appears in a provider's live list.

    Exact match, plus one narrow exception: Anthropic lists dated snapshots
    (``claude-haiku-4-5-20251001``) while the alias you actually call is undated
    (``claude-haiku-4-5``). Matching only exactly marked a model that
    demonstrably works as unavailable — and it was the cheapest one scoring 5/5,
    so the bug pointed away from the answer this page exists to find.

    The suffix must be **eight digits**. Plain ``startswith(model + "-")`` is
    wrong in the other direction: ``gemini-3.5-flash-lite`` would vouch for
    ``gemini-3.5-flash``, so a withdrawn model would read as available purely
    because a differently-sized sibling survived. A date is a snapshot of the
    same model; ``-lite`` is a different one.

    ``None``/empty live list means "we didn't ask" or "we couldn't reach it",
    both answered ``True``: absence of evidence is not a withdrawal.
    """
    if not live:
        return True
    return any(
        offered == model
        or (offered.startswith(f"{model}-") and _DATE_SUFFIX.match(offered[len(model) + 1 :]))
        for offered in live
    )


@router.get("/stats/llm", response_model=LlmStatsOut)
def llm_stats(
    db: Session = Depends(get_db), task: str | None = None, live: bool = False
) -> LlmStatsOut:
    """What each model backend has actually cost and delivered (Phase 20b).

    Separate from ``/stats`` because it answers a different question for a
    different reader: ``/stats`` is about the job search, this is about the tool
    running it. Folding it in would put "is Gemini worth it" next to "how many
    interviews did I get", and the second one is not improved by the first.
    """
    from jobpilot.llm.pricing import PRICES
    from jobpilot.llm.redact import shadowed_secrets
    from jobpilot.llm.registry import PROVIDERS, api_key, list_models

    tasks: tuple[str, ...] = ("tailor", "letter", "classify")
    cfg = get_config().llm
    rows = backend_stats(db, task=task)

    # `live` is opt-in: it costs one round-trip per provider, and the page is
    # useful without it. Off by default so opening the dashboard is free.
    live_models = {name: list_models(name) for name in PROVIDERS} if live else {}

    catalogue = [
        ModelOptionOut(
            provider=provider,
            model=model,
            input_per_mtok=rate[0],
            output_per_mtok=rate[1],
            # Unknown (no live list fetched) is reported as available rather
            # than hidden: absence of evidence is not a withdrawn model.
            available=_offered(model, live_models.get(provider)),
        )
        for (provider, model), rate in sorted(PRICES.items())
        if provider in PROVIDERS
    ]

    spend: list[ProviderSpendOut] = []
    for name in PROVIDERS:
        mine = [r for r in rows if r["provider"] == name]
        spent = sum(r["cost_usd"] or 0.0 for r in mine)
        budget = cfg.budget_usd.get(name)
        spend.append(
            ProviderSpendOut(
                provider=name,
                has_key=bool(api_key(name)),
                spent_usd=round(spent, 6),
                unpriced_rounds=sum(r["unpriced_rounds"] for r in mine),
                budget_usd=budget,
                # Floored at zero: a negative "remaining" would suggest we know
                # the account is overdrawn, and we do not know that at all.
                remaining_usd=None if budget is None else round(max(budget - spent, 0.0), 6),
                models=live_models.get(name, []),
            )
        )

    return LlmStatsOut(
        min_sample=MIN_SAMPLE,
        backends=rows,
        catalogue=catalogue,
        spend=spend,
        total_spent_usd=round(sum(s.spent_usd for s in spend), 6),
        providers={name: bool(api_key(name)) for name in PROVIDERS},
        shadowed_env=shadowed_secrets(),
        configured={t: cfg.for_task(t) for t in tasks},
        warnings={t: llm.warnings(t) for t in tasks},
        blockers={t: llm.blocker(t) for t in tasks},
    )
