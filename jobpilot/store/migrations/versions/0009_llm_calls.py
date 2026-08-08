"""what each model call cost, so a backend can be chosen on evidence

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08

Phase 20 measured two backends by hand and wrote the numbers into a document.
That answered the question once. This table answers it continuously, which
matters now that the backend is a per-task setting anyone can change: "is the
cheap model good enough for classify" is not a question to re-litigate from
memory.

One row per **round**, not per task. A backend that is cheap per call and needs
the corrective retry half the time is not cheap, and a table that only kept the
accepted round would make it look like the best option in the very column people
sort by.

``cost_usd`` is nullable and stays NULL for a model missing from
``llm/pricing.py``. That is a different fact from "it was free" — and price
tables go stale by sitting still, so the nullable case is the normal one, not the
edge case.

Its own table rather than a column on ``applications``: this is data to GROUP BY,
and most of it (tailor rounds for jobs never applied to) belongs to no
application at all. ``ON DELETE SET NULL`` on both foreign keys for the same
reason — deleting a job should not delete the record of what it cost to consider
it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # String, not an enum: the set of tasks will grow, and ALTER TYPE cannot
        # run inside a transaction block — the lesson from 0007.
        sa.Column("task", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default="false"),
        # Text, not VARCHAR: this holds an exception message written by an SDK,
        # and Postgres would be the one to discover it was too long — mid-flush,
        # in the middle of recording that something already went wrong.
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "job_id",
            sa.String(128),
            sa.ForeignKey(f"{SCHEMA}.jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    # The three columns every aggregate groups by, plus the one it orders by.
    op.create_index("ix_llm_calls_task", "llm_calls", ["task"], schema=SCHEMA)
    op.create_index("ix_llm_calls_provider", "llm_calls", ["provider"], schema=SCHEMA)
    op.create_index("ix_llm_calls_model", "llm_calls", ["model"], schema=SCHEMA)
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], schema=SCHEMA)
    op.create_index("ix_llm_calls_job_id", "llm_calls", ["job_id"], schema=SCHEMA)
    op.create_index("ix_llm_calls_application_id", "llm_calls", ["application_id"], schema=SCHEMA)


def downgrade() -> None:
    for name in (
        "ix_llm_calls_application_id",
        "ix_llm_calls_job_id",
        "ix_llm_calls_created_at",
        "ix_llm_calls_model",
        "ix_llm_calls_provider",
        "ix_llm_calls_task",
    ):
        op.drop_index(name, table_name="llm_calls", schema=SCHEMA)
    op.drop_table("llm_calls", schema=SCHEMA)
