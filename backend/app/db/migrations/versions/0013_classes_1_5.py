"""Classes 1 to 5: a teacher's class band may now be 4 or 5.

0002 limited `teachers.grade_band` to 1, 2, 3 or multi. Postgres named that inline check
`teachers_grade_band_check`; it is replaced by one that also allows 4 and 5. (Revision 0012 was
planned for a language change that was not needed, so the chain goes 0011 to 0013.)

Downgrading maps classes 4 and 5 to 'multi' first, since the old check would refuse them.

Revision ID: 0013
Revises: 0011
"""

from alembic import op

revision = "0013"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table teachers drop constraint if exists teachers_grade_band_check")
    op.execute(
        "alter table teachers add constraint teachers_grade_band_check "
        "check (grade_band in ('1', '2', '3', '4', '5', 'multi'))"
    )


def downgrade() -> None:
    op.execute("update teachers set grade_band = 'multi' where grade_band in ('4', '5')")
    op.execute("alter table teachers drop constraint if exists teachers_grade_band_check")
    op.execute(
        "alter table teachers add constraint teachers_grade_band_check "
        "check (grade_band in ('1', '2', '3', 'multi'))"
    )
