"""Pydantic response schemas for the API (serialize ORM rows)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from jobpilot.store.models import JobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    url: str
    title: str
    company: str
    location: str | None
    salary: str | None
    level: str | None
    posted_at: datetime | None
    status: JobStatus
    match_score: float
    apply_channel: str | None
    apply_target: str | None
    crawled_at: datetime | None


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_source: dict[str, int]
