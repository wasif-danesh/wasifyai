"""the assistant's messages become a tree (ADR-0082, stage CU2)

Every message gets a `parent_id` and every conversation a `head_id`, so a message can be edited
and an answer regenerated without losing the earlier version: the new one is a sibling.
Conversations that exist already are chains: each message's parent is the message before it, and
their head is empty (the store reads that as the last message). The desktop profile's SQLite file
gets the same columns when the store first opens it.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    op.add_column("messages", sa.Column("parent_id", sa.Text, nullable=True))
    op.add_column("conversations", sa.Column("head_id", sa.Text, nullable=True))
    op.execute(
        "UPDATE messages m SET parent_id = p.id FROM messages p "
        "WHERE p.conversation_id = m.conversation_id AND p.seq = m.seq - 1"
    )


def downgrade() -> None:
    op.drop_column("conversations", "head_id")
    op.drop_column("messages", "parent_id")
