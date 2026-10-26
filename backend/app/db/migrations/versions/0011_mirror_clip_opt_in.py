"""Opt-in mirror clips: the teacher's consent flag, and what a stored clip needs to play back.

`mirror_clips` has existed since 0002 but nothing wrote to it. A clip is kept only for a teacher
who said yes (`teachers.clip_opt_in`), and needs its mime type to be sent back as audio and its
creation time to tell the first clip from the latest.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table teachers add column clip_opt_in boolean not null default false")
    op.execute("alter table teachers add column clip_opt_in_at timestamptz")
    op.execute("alter table mirror_clips add column mime text not null default 'audio/ogg'")
    op.execute("alter table mirror_clips add column created_at timestamptz not null default now()")
    op.execute(
        "create index mirror_clips_teacher_created_idx on mirror_clips (teacher_id, created_at)"
    )


def downgrade() -> None:
    op.execute("drop index if exists mirror_clips_teacher_created_idx")
    op.execute("alter table mirror_clips drop column created_at")
    op.execute("alter table mirror_clips drop column mime")
    op.execute("alter table teachers drop column clip_opt_in_at")
    op.execute("alter table teachers drop column clip_opt_in")
