"""Remember the topic of the latest plan and a practice in progress.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table teachers add column last_topic_id text")
    op.execute("alter table teachers add column rehearsal_json text")


def downgrade() -> None:
    op.execute("alter table teachers drop column rehearsal_json")
    op.execute("alter table teachers drop column last_topic_id")
