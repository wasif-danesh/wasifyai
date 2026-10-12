"""lipsyncs: talking-character clips of the wasifyai-lipsync product (ADR-0044)

Like videos: a row exists from the moment a run starts (status "working"), then "done" (with its
files) or "failed" (with a message for the user). The picture and the voice are not kept.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.create_table(
        "lipsyncs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
        sa.Column("source", sa.Text, nullable=False),  # script | audio
        sa.Column("status", sa.Text, nullable=False),  # working | done | failed
        sa.Column("script", sa.Text, nullable=False, server_default=""),
        sa.Column("style", sa.Text, nullable=False, server_default=""),
        sa.Column("transcript", sa.Text, nullable=False, server_default=""),
        sa.Column("seconds", sa.Float, nullable=False, server_default="0"),
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
        "ix_lipsyncs_user_created",
        "lipsyncs",
        ["tenant_id", "product_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_lipsyncs_user_created", table_name="lipsyncs")
    op.drop_table("lipsyncs")
