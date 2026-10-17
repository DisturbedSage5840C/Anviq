"""Remember where a teacher was before an unconfirmed delete request.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table teachers add column resume_state text")


def downgrade() -> None:
    op.execute("alter table teachers drop column resume_state")
