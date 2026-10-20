"""An index for the reminder claim, so each quarter-hour tick reads only who could be due.

The claim picks opted-in, consenting teachers by `reminder_time` and takes the first batch. With
the index in the same order as the claim's `order by`, Postgres reads the batch off the index
instead of scanning and sorting every teacher.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "create index teachers_reminder_due on teachers (reminder_time, id) "
        "where reminders_opt_in and consent_at is not null"
    )


def downgrade() -> None:
    op.execute("drop index if exists teachers_reminder_due")
