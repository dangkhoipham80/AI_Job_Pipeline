"""add cv_versions.meta for tailor output

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27

Phase 5 stores the tailor plan alongside the version it produced: match score,
requirement classification, gaps, and the change list the reviewer reads. Keeping
it on ``cv_versions`` means a tailored CV and the reasoning behind it can never
drift apart — they are the same row.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column(
        "cv_versions",
        sa.Column(
            "meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema=SCHEMA,
    )
    # Reviewers filter by score; the column is only populated on agent versions.
    op.create_index(
        "ix_cv_versions_scope_job_id",
        "cv_versions",
        ["scope", "job_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_cv_versions_scope_job_id", table_name="cv_versions", schema=SCHEMA)
    op.drop_column("cv_versions", "meta", schema=SCHEMA)
