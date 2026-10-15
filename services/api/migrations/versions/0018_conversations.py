"""conversations and messages of the assistant (ADR-0057 decision 3)

Ids are text and times are UTC ISO strings, so the desktop profile's SQLite file and this
database share one implementation. Both tables carry tenant_id and product_id like every product
table (rule 7).

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_conversations_user_updated",
        "conversations",
        ["tenant_id", "product_id", "user_id", "updated_at"],
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("conversation_id", sa.Text, nullable=False),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("parts", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ux_messages_conversation_seq", "messages", ["conversation_id", "seq"], unique=True
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
