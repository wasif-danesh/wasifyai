"""videos: clips of the wasifyai-video product, including ones still being made (ADR-0037)

A row is created when a run starts, with status "working", and set to "done" (with its files) or
"failed" (with a message for the user). The files are in object storage; the row holds their keys,
relative to the user's prefix.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("seconds", sa.Integer, nullable=False),
        sa.Column("frames", sa.Integer, nullable=False),
        sa.Column("fps", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("video_key", sa.Text),
        sa.Column("poster_key", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_videos_user_created", "videos", ["tenant_id", "product_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("videos")
