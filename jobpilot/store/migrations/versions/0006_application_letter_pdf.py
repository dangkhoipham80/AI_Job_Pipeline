"""record the built cover letter PDF alongside the text

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07

SKILL.md §2 step 4 asks for a cover letter *document*; until now the letter only
existed as the plain text that became the email body. The PDF is built from the
same fields and lives next to the tailored CV.

A second column rather than reusing ``cover_letter_path``: the two artifacts fail
apart. The text can exist with no PDF (Docker down, LaTeX error) and that is a
degraded application, not a failed one. One column would make "the build broke"
look identical to "there is no letter" — and the reason lands in
``meta['letter']['pdf_error']`` so it never has to be guessed at.

Nullable, no backfill: applications sent before this migration genuinely have no
letter PDF, and inventing a path to a file that was never built would be worse
than NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "jobpilot"


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("cover_letter_pdf_path", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("applications", "cover_letter_pdf_path", schema=SCHEMA)
