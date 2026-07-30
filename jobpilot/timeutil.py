"""Shared time helpers. Fixed +07:00 (Asia/Ho_Chi_Minh, no DST) — avoids a
tzdata dependency on Windows and keeps crawl/API timestamps consistent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))


def vn_now() -> datetime:
    """Current time in Vietnam (tz-aware)."""
    return datetime.now(VN_TZ)
