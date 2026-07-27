"""add applications.meta and created_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27

Phase 6 records how an application was dispatched, not just that it was: the
email summary (recipient, subject, whether a test redirect applied) or the
portal handoff package. ``created_at`` separates "prepared" from "submitted",
which matters for dry runs and for portal jobs still waiting on the user.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "applications",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    # The board reads applications newest-first per status.
    op.create_index("ix_applications_result", "applications", ["result"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_applications_result", table_name="applications", schema=SCHEMA)
    op.drop_column("applications", "created_at", schema=SCHEMA)
    op.drop_column("applications", "meta", schema=SCHEMA)
