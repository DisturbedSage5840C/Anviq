"""Harden public_trends against predicate pushdown and differencing.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# security_barrier stops a caller's WHERE (and any leaky function in it) from being pushed below
# the HAVING into suppressed cells. Teacher counts are floored to a multiple of 5 and averages
# rounded to one decimal, so one teacher joining or leaving between weeks cannot be read off the
# change. This lowers differencing risk; it is not differential privacy (see docs/DPIA.md).
HARDENED_VIEW = """
    create or replace view public_trends with (security_barrier = true) as
    select coalesce(cluster_code, 'unassigned') as cluster_code,
           move_id,
           iso_week,
           (count(distinct teacher_id) / 5) * 5 as n_teachers,
           round(avg(met_delta), 1) as avg_improvement,
           round(avg(sessions), 1) as avg_sessions
    from teacher_week_stats
    group by 1, 2, 3
    having count(distinct teacher_id) >= 20
"""

PREVIOUS_VIEW = """
    create or replace view public_trends with (security_barrier = false) as
    select coalesce(cluster_code, 'unassigned') as cluster_code,
           move_id,
           iso_week,
           count(distinct teacher_id) as n_teachers,
           round(avg(met_delta), 2) as avg_improvement,
           round(avg(sessions), 1) as avg_sessions
    from teacher_week_stats
    group by 1, 2, 3
    having count(distinct teacher_id) >= 20
"""


def upgrade() -> None:
    op.execute(HARDENED_VIEW)


def downgrade() -> None:
    op.execute(PREVIOUS_VIEW)
