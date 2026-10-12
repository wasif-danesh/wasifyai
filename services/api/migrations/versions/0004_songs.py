"""songs: finished songs of the wasifyai-music product

Product tables live in the shared database and carry tenant_id and product_id like every
other table (rule 7).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_table(
        "songs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("lyrics", sa.Text, nullable=False),
        sa.Column("style", sa.Text, nullable=False),
        sa.Column("audio_key", sa.Text, nullable=False),
        sa.Column("cover_key", sa.Text),  # null when the cover job failed
        sa.Column("status", sa.Text, nullable=False, server_default="done"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_songs_user_created", "songs", ["tenant_id", "product_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("songs")
