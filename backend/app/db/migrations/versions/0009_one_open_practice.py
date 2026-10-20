"""A teacher has at most one practice open at a time, and the log's lookups are indexed.

The practice log opens a session on the first scored turn and closes it when the practice ends.
The unique index lets the log say "open one unless there is already one" in a single, race-free
upsert. Any older duplicate is closed first so the index can be built.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        update sessions set ended_at = started_at
        where kind = 'rehearse' and ended_at is null
          and id not in (
            select distinct on (teacher_id) id from sessions
            where kind = 'rehearse' and ended_at is null
            order by teacher_id, started_at desc, id
          )
        """
    )
    op.execute(
        "create unique index sessions_one_open_practice on sessions (teacher_id) "
        "where kind = 'rehearse' and ended_at is null"
    )
    op.execute(
        "create index sessions_teacher_move_started on sessions (teacher_id, move_id, started_at)"
    )
    op.execute("create index turns_session on turns (session_id)")


def downgrade() -> None:
    op.execute("drop index if exists turns_session")
    op.execute("drop index if exists sessions_teacher_move_started")
    op.execute("drop index if exists sessions_one_open_practice")
