"""record what happened after the application went out

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-07

Phase 15 gave the pipeline a nudge; it still had nowhere to put the answer. The
board could say "submitted 12 days ago" but never "they replied on day 3 and
interviewed on day 9", so the one question worth asking about a job search —
*is this working?* — had no data behind it.

Two structures, on purpose. ``applications.outcome_stage`` is the denormalized
latest state, because the board renders up to 200 cards and should not pay a
subquery for each. ``application_events`` is the append-only log, because rates
need the *sequence*: an application rejected after two interviews and one
rejected on day one both collapse to "rejected" in a single column, and telling
them apart is the entire point of measuring.

``event_type`` is a VARCHAR rather than a Postgres enum. The value set will grow
(Phase 19 brings employer-reply subtypes from the inbox), and ``ALTER TYPE ...
ADD VALUE`` cannot run inside a transaction block, so every future value would
cost an awkward out-of-band migration. Validation lives in the API layer where a
bad value is a 422 instead of a 500.

No backfill. Existing rows get ``outcome_stage = NULL``, which reads as "nothing
recorded yet" — the truth. Inventing ``ghosted`` for every old application would
manufacture exactly the statistic this table exists to measure honestly.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("outcome_stage", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        # When it happened, which is not when it was typed in — Phase 19 records
        # replies days after the fact and time-to-reply must not absorb that lag.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_retracted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        # Where the follow-up cadence stood before this event stopped it, so a
        # fully retracted mistake can hand the reminder back instead of leaving
        # it stopped forever with no outcome to justify it.
        sa.Column("prev_followup_stage", sa.String(32), nullable=True),
        sa.Column("prev_followup_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    # One index per question actually asked: "the history of this application"
    # (board card) and "what happened in this window" (Phase 20 rates).
    op.create_index(
        "ix_application_events_application_id",
        "application_events",
        ["application_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_application_events_event_type",
        "application_events",
        ["event_type"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_application_events_occurred_at",
        "application_events",
        ["occurred_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_events_occurred_at", table_name="application_events", schema=SCHEMA
    )
    op.drop_index(
        "ix_application_events_event_type", table_name="application_events", schema=SCHEMA
    )
    op.drop_index(
        "ix_application_events_application_id", table_name="application_events", schema=SCHEMA
    )
    op.drop_table("application_events", schema=SCHEMA)
    op.drop_column("applications", "outcome_stage", schema=SCHEMA)
