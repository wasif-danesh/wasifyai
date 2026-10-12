"""speeches: finished text to speech results of the wasifyai-tts product (ADR-0042)

The file is in object storage; the row holds its key, relative to the user's prefix, and the words
that were spoken (the words are what search finds, ADR-0041).

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "speeches",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("gender", sa.Text, nullable=False),
        sa.Column("voice", sa.Text, nullable=False),
        sa.Column("characters", sa.Integer, nullable=False),
        sa.Column("seconds", sa.Float, nullable=False),
        sa.Column("audio_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_speeches_user_created", "speeches", ["tenant_id", "product_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("speeches")
