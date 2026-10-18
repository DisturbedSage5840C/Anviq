"""Remember the day a teacher was last reminded, so a reminder goes out at most once a day.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table teachers add column last_reminded_on date")


def downgrade() -> None:
    op.execute("alter table teachers drop column last_reminded_on")
