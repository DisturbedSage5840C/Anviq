"""Core schema: private per-teacher tables, row-level security, roles, k-anonymous trends view.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Every table that holds anything about a teacher. RLS is on for all of them and dashboard_ro
# gets no grant on any of them.
PRIVATE_TABLES = (
    "teachers",
    "consents",
    "sessions",
    "turns",
    "move_progress",
    "mirror_clips",
    "teacher_week_stats",
    "deletion_log",
    "llm_usage",
    "speech_usage",
)

ROLES = ("app_rw", "dashboard_ro")

CREATE_STATEMENTS = (
    """
    create table teachers (
        id uuid primary key default gen_random_uuid(),
        phone_hash bytea not null unique,
        wa_id_enc bytea not null,
        lang text not null check (lang in ('hi', 'en')),
        grade_band text check (grade_band in ('1', '2', '3', 'multi')),
        cluster_code text,
        state text not null default 'NEW',
        current_move smallint not null default 1 check (current_move between 1 and 6),
        cycle_no smallint not null default 1,
        cycle_started_at date,
        reminders_opt_in boolean not null default false,
        reminder_time time,
        consent_version text,
        consent_at timestamptz,
        created_at timestamptz not null default now(),
        last_active_at timestamptz not null default now()
    )
    """,
    """
    create table consents (
        id uuid primary key default gen_random_uuid(),
        teacher_id uuid not null references teachers (id) on delete cascade,
        version text not null,
        text_sha256 text not null,
        channel text not null check (channel in ('whatsapp', 'web')),
        granted_at timestamptz not null default now(),
        revoked_at timestamptz
    )
    """,
    """
    create table sessions (
        id uuid primary key default gen_random_uuid(),
        teacher_id uuid not null references teachers (id) on delete cascade,
        kind text not null check (kind in ('plan', 'rehearse', 'reflect', 'ask', 'mirror')),
        move_id smallint check (move_id between 1 and 6),
        topic_id text,
        week text check (week in ('A', 'B')),
        started_at timestamptz not null default now(),
        ended_at timestamptz,
        summary_json jsonb
    )
    """,
    """
    create table turns (
        id uuid primary key default gen_random_uuid(),
        session_id uuid not null references sessions (id) on delete cascade,
        role text not null check (role in ('teacher', 'child', 'coach')),
        text_scrubbed text not null,
        malrule_id text,
        child_name text,
        criteria_json jsonb,
        met_count smallint check (met_count between 0 and 4),
        latency_ms integer,
        created_at timestamptz not null default now()
    )
    """,
    "create index turns_created_at_idx on turns (created_at)",
    """
    create table move_progress (
        teacher_id uuid not null references teachers (id) on delete cascade,
        move_id smallint not null check (move_id between 1 and 6),
        cycle_no smallint not null,
        day1_turn_id uuid references turns (id) on delete set null,
        day14_turn_id uuid references turns (id) on delete set null,
        sessions_completed integer not null default 0,
        status text not null default 'active' check (status in ('active', 'done')),
        primary key (teacher_id, move_id, cycle_no)
    )
    """,
    """
    create table mirror_clips (
        id uuid primary key default gen_random_uuid(),
        teacher_id uuid not null references teachers (id) on delete cascade,
        turn_id uuid references turns (id) on delete set null,
        audio_enc bytea not null,
        expires_at timestamptz not null
    )
    """,
    "create index mirror_clips_expires_at_idx on mirror_clips (expires_at)",
    """
    create table teacher_week_stats (
        teacher_id uuid not null references teachers (id) on delete cascade,
        cluster_code text,
        move_id smallint not null check (move_id between 1 and 6),
        iso_week text not null check (iso_week ~ '^[0-9]{4}-W[0-9]{2}$'),
        met_delta numeric(4, 2) not null,
        sessions integer not null default 0,
        primary key (teacher_id, move_id, iso_week)
    )
    """,
    """
    create table deletion_log (
        id uuid primary key default gen_random_uuid(),
        phone_hash_prefix8 text not null check (length(phone_hash_prefix8) = 16),
        requested_at timestamptz not null default now(),
        completed_at timestamptz
    )
    """,
    """
    create table llm_usage (
        id bigint generated always as identity primary key,
        purpose text not null,
        model text not null,
        in_tok integer not null,
        out_tok integer not null,
        cache_read integer not null default 0,
        cache_write integer not null default 0,
        latency_ms integer not null,
        est_cost_usd numeric(10, 6) not null,
        created_at timestamptz not null default now()
    )
    """,
    """
    create table speech_usage (
        id bigint generated always as identity primary key,
        provider text not null,
        kind text not null check (kind in ('stt', 'tts')),
        seconds_or_chars numeric(10, 2) not null,
        est_cost_inr numeric(10, 4) not null,
        created_at timestamptz not null default now()
    )
    """,
    # Public reference corpus (NISHTHA / NIPUN), not teacher data, so no RLS.
    """
    create table doc_chunks (
        id uuid primary key default gen_random_uuid(),
        source text not null,
        course_no smallint,
        module text,
        section_no text,
        section_title text,
        page integer,
        lang text not null check (lang in ('hi', 'en')),
        text text not null,
        context_line text,
        embedding vector(1024),
        tsv tsvector generated always as (to_tsvector('simple', text)) stored
    )
    """,
    "create index doc_chunks_embedding_idx on doc_chunks using hnsw (embedding vector_cosine_ops)",
    "create index doc_chunks_tsv_idx on doc_chunks using gin (tsv)",
)

# Grants dashboard_ro nothing but this view. The view runs with its owner's rights, so the
# HAVING clause is the only way through to teacher_week_stats: k-anonymity lives in SQL.
# k = 20, frozen into the migration; tests/db/test_schema.py pins the 19/20 boundary.
TRENDS_VIEW = """
    create view public_trends as
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


def _create_role_if_missing(role: str) -> None:
    # NOLOGIN: ops sets a password out of band, so no credential ever lives in the repo.
    op.execute(
        f"""
        do $$
        begin
            if not exists (select from pg_roles where rolname = '{role}') then
                create role {role} nologin;
            end if;
        end
        $$
        """
    )


def upgrade() -> None:
    for role in ROLES:
        _create_role_if_missing(role)
    for statement in CREATE_STATEMENTS:
        op.execute(statement)
    op.execute(TRENDS_VIEW)

    for table in PRIVATE_TABLES:
        op.execute(f"alter table {table} enable row level security")
        op.execute(
            f"create policy {table}_app_rw on {table} for all to app_rw "
            "using (true) with check (true)"
        )
        op.execute(f"grant select, insert, update, delete on {table} to app_rw")
    op.execute("grant select, insert, update, delete on doc_chunks to app_rw")
    op.execute("grant usage on all sequences in schema public to app_rw")
    op.execute("grant select on public_trends to dashboard_ro")


def downgrade() -> None:
    op.execute("drop view if exists public_trends")
    # Roles are cluster-wide and may be shared with other databases, so they are kept.
    for table in ("doc_chunks", *reversed(PRIVATE_TABLES)):
        op.execute(f"drop table if exists {table} cascade")
