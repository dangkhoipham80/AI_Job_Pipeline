"""propose outcomes from employer replies sitting in your mailbox

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-07

Phase 18 gave applications an outcome to carry. Recording one by hand works for
about a fortnight, and then the numbers stop describing the job search and start
describing how disciplined you were about typing. The answers were in the inbox
the whole time.

A suggestion is not an outcome, and this is a separate table for exactly that
reason. Putting proposals in ``application_events`` with a flag would mean every
count in ``outcome_counts`` had to remember to exclude them — and the phase
before this one shipped a bug where one aggregate forgot a distinction just like
that. Numbers read from the event log stay numbers about things that happened.

``mail_key`` is the message's ``Message-ID``, not its IMAP uid: uids are
per-folder and get re-issued whenever the server's UIDVALIDITY changes, so a uid
key would silently re-classify — and re-bill for — the entire mailbox the first
time that happened.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.create_table(
        "inbox_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mail_key", sa.String(512), nullable=False),
        sa.Column("mail_from", sa.String(320), nullable=False, server_default=""),
        # Text rather than VARCHAR: a subject line is written by a stranger, and
        # Postgres would be the one to discover it was too long — mid-flush,
        # taking the rest of the sync with it.
        sa.Column("mail_subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("mail_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_confidence", sa.String(16), nullable=False, server_default=""),
        sa.Column("match_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False, server_default=""),
        sa.Column("round_label", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_inbox_suggestions_application_id",
        "inbox_suggestions",
        ["application_id"],
        schema=SCHEMA,
    )
    op.create_index("ix_inbox_suggestions_status", "inbox_suggestions", ["status"], schema=SCHEMA)
    op.create_index("ix_inbox_suggestions_verdict", "inbox_suggestions", ["verdict"], schema=SCHEMA)
    # Re-running the sync must be free and silent, not duplicate every reply.
    op.create_unique_constraint(
        "uq_inbox_suggestions_application_mail",
        "inbox_suggestions",
        ["application_id", "mail_key"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_inbox_suggestions_application_mail",
        "inbox_suggestions",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_index("ix_inbox_suggestions_verdict", table_name="inbox_suggestions", schema=SCHEMA)
    op.drop_index("ix_inbox_suggestions_status", table_name="inbox_suggestions", schema=SCHEMA)
    op.drop_index(
        "ix_inbox_suggestions_application_id", table_name="inbox_suggestions", schema=SCHEMA
    )
    op.drop_table("inbox_suggestions", schema=SCHEMA)
