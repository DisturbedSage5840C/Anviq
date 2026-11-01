"""NCERT textbook metadata on `doc_chunks`.

A textbook chunk knows its class, subject, book and chapter, so retrieval can be limited to the
teacher's class and a citation can name the chapter. All columns are nullable: the NISHTHA, NIPUN
and Handbook rows already in the table keep working and simply leave them empty. `doc_chunks`
is public reference data, so no row-level security applies. The existing `tsv` column and its GIN
index are untouched.

Downgrading drops the textbook rows first (they cannot be labelled without these columns), then
the columns.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table doc_chunks add column if not exists class_level smallint")
    op.execute("alter table doc_chunks add column if not exists subject text")
    op.execute("alter table doc_chunks add column if not exists book_code text")
    op.execute("alter table doc_chunks add column if not exists chapter_no smallint")
    op.execute("alter table doc_chunks add column if not exists chapter_title text")
    op.execute(
        "alter table doc_chunks add constraint doc_chunks_class_level_check "
        "check (class_level is null or class_level between 1 and 5)"
    )
    op.execute(
        "create index if not exists doc_chunks_book_idx on doc_chunks (book_code, class_level)"
    )


def downgrade() -> None:
    op.execute("drop index if exists doc_chunks_book_idx")
    op.execute("delete from doc_chunks where book_code is not null")
    op.execute("alter table doc_chunks drop constraint if exists doc_chunks_class_level_check")
    for column in ("chapter_title", "chapter_no", "book_code", "subject", "class_level"):
        op.execute(f"alter table doc_chunks drop column if exists {column}")
