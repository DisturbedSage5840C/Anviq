"""Demo codes for the web room: hashed at rest, seven-day expiry, a per-code turn budget.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table demo_codes (
            code_hash bytea primary key,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null,
            turns_left integer not null check (turns_left >= 0)
        )
        """
    )
    op.execute("alter table demo_codes enable row level security")
    op.execute(
        "create policy demo_codes_app_rw on demo_codes for all to app_rw "
        "using (true) with check (true)"
    )
    op.execute("grant select, insert, update, delete on demo_codes to app_rw")


def downgrade() -> None:
    op.execute("drop table demo_codes")
