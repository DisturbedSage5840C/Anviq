"""Store each corpus chunk's citation label, built from its metadata at ingestion.

Ask Anviq shows this label as the source line, so it must come from the document's own metadata
and never from model output (plan section 4.8).

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table doc_chunks add column label text not null default ''")
    op.execute("create index doc_chunks_lang_idx on doc_chunks (lang)")


def downgrade() -> None:
    op.execute("drop index doc_chunks_lang_idx")
    op.execute("alter table doc_chunks drop column label")
