"""link a job to the crawl that discovered it

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28

Until now a job knew *when* it was crawled but not *which run* found it, so
"what did the 14:30 crawl turn up?" was unanswerable — the Runs page could show
that a crawl inserted 7 jobs but not which 7.

``run_id`` records the run that **first discovered** the job and is not touched
on re-crawl. That is the useful reading: a job belongs to the crawl that found
it, not to every crawl that has seen it since.

ON DELETE SET NULL: deleting old run history must not delete jobs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column("jobs", sa.Column("run_id", sa.Integer(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_jobs_run_id_runs",
        "jobs",
        "runs",
        ["run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    # The Runs page groups jobs by run; the Jobs page filters by crawl time.
    op.create_index("ix_jobs_run_id", "jobs", ["run_id"], schema=SCHEMA)
    op.create_index("ix_jobs_crawled_at", "jobs", ["crawled_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_jobs_crawled_at", table_name="jobs", schema=SCHEMA)
    op.drop_index("ix_jobs_run_id", table_name="jobs", schema=SCHEMA)
    op.drop_constraint("fk_jobs_run_id_runs", "jobs", schema=SCHEMA, type_="foreignkey")
    op.drop_column("jobs", "run_id", schema=SCHEMA)
