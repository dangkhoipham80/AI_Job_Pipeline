"""initial jobpilot schema

Revision ID: 0001
Revises:
Create Date: 2026-07-09

Creates the core tables (jobs, applications, edits, runs, cv_versions) in the
``jobpilot`` Postgres schema, plus the ``job_status`` enum and a GIN index on
``jobs.payload`` for JD full-text/JSON search.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"

_STATUSES = (
    "DISCOVERED",
    "SHORTLISTED",
    "TAILORING",
    "REVIEW",
    "APPROVED",
    "SUBMITTING",
    "SUBMITTED",
    "FAILED",
    "SKIPPED",
)


def upgrade() -> None:
    bind = op.get_bind()
    # create_type=False so create_table below won't re-emit CREATE TYPE (we create
    # it once, explicitly, here — otherwise Postgres errors on the duplicate).
    job_status = postgresql.ENUM(*_STATUSES, name="job_status", schema=SCHEMA, create_type=False)
    job_status.create(bind, checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("location", sa.String(256)),
        sa.Column("salary", sa.String(128)),
        sa.Column("level", sa.String(32)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("status", job_status, nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("apply_channel", sa.String(32)),
        sa.Column("apply_target", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "crawled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_jobs_source", "jobs", ["source"], schema=SCHEMA)
    op.create_index("ix_jobs_level", "jobs", ["level"], schema=SCHEMA)
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"], schema=SCHEMA)
    op.create_index("ix_jobs_status", "jobs", ["status"], schema=SCHEMA)
    op.create_index("ix_jobs_match_score", "jobs", ["match_score"], schema=SCHEMA)
    op.create_index(
        "ix_jobs_payload_gin", "jobs", ["payload"], schema=SCHEMA, postgresql_using="gin"
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("cv_pdf_path", sa.Text()),
        sa.Column("cover_letter_path", sa.Text()),
        sa.Column("channel", sa.String(32)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.String(32)),
        sa.Column("error_msg", sa.Text()),
        sa.ForeignKeyConstraint(
            ["job_id"],
            [f"{SCHEMA}.jobs.id"],
            name="fk_applications_job_id_jobs",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_applications_job_id", "applications", ["job_id"], schema=SCHEMA)

    op.create_table(
        "edits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], [f"{SCHEMA}.jobs.id"], name="fk_edits_job_id_jobs", ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_edits_job_id", "edits", ["job_id"], schema=SCHEMA)

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("stats", postgresql.JSONB(), nullable=False),
        sa.Column("log_ref", sa.Text()),
        schema=SCHEMA,
    )
    op.create_index("ix_runs_kind", "runs", ["kind"], schema=SCHEMA)

    op.create_table(
        "cv_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("job_id", sa.String(128)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("tex_snapshot", sa.Text()),
        sa.Column("theme", postgresql.JSONB(), nullable=False),
        sa.Column("author", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], [f"{SCHEMA}.jobs.id"], name="fk_cv_versions_job_id_jobs", ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_cv_versions_scope", "cv_versions", ["scope"], schema=SCHEMA)
    op.create_index("ix_cv_versions_job_id", "cv_versions", ["job_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("cv_versions", schema=SCHEMA)
    op.drop_table("runs", schema=SCHEMA)
    op.drop_table("edits", schema=SCHEMA)
    op.drop_table("applications", schema=SCHEMA)
    op.drop_table("jobs", schema=SCHEMA)
    postgresql.ENUM(name="job_status", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
