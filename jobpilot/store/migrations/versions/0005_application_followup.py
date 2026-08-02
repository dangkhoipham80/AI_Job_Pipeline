"""track when an application is due a follow-up

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-02

The pipeline ended at "submitted" and then went quiet, which is where most
applications die. Nothing recorded that a week had passed with no reply, so
following up depended on remembering — and remembering is exactly what a tool
like this exists to replace.

Two columns rather than a derived date: ``followup_stage`` is *where you are* in
the cadence and ``next_followup_at`` is *when the next step is due*. Deriving
the date from ``submitted_at`` alone would be wrong the moment you follow up
early, follow up late, or get a reply and stop — all of which are normal.

Both nullable: a dry run sends nothing, so it is owed no follow-up, and NULL
says that more honestly than a date in the past would.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "applications",
        sa.Column("followup_stage", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    # The board's only new question is "what is due?", which is a range scan
    # over this column and nothing else.
    op.create_index(
        "ix_applications_next_followup_at",
        "applications",
        ["next_followup_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_applications_next_followup_at", table_name="applications", schema=SCHEMA)
    op.drop_column("applications", "followup_stage", schema=SCHEMA)
    op.drop_column("applications", "next_followup_at", schema=SCHEMA)
