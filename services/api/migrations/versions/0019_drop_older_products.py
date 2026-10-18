"""drop the tables of the older music, speech, transcript and lip sync products

The voice product replaced them (docs/phase3-web-parity-plan.md, W6) and the owner chose to
delete what they had made rather than migrate it. This deletes those rows, and the search index
entries that pointed at them. It does not touch the files in object storage:
`scripts/purge_older_products.py` removes those.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"

OLDER = ("wasifyai-music", "wasifyai-tts", "wasifyai-stt", "wasifyai-lipsync")
TABLES = ("songs", "speeches", "transcripts", "lipsyncs")


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _owner() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
    ]


def upgrade() -> None:
    names = ", ".join(f"'{p}'" for p in OLDER)
    op.execute(f"DELETE FROM creation_index WHERE product_id IN ({names})")
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    """The empty tables come back (the rows do not)."""
    op.create_table(
        "songs", sa.Column("id", sa.Uuid, primary_key=True), *_owner(),
        sa.Column("title", sa.Text, nullable=False), sa.Column("lyrics", sa.Text, nullable=False),
        sa.Column("style", sa.Text, nullable=False),
        sa.Column("audio_key", sa.Text, nullable=False), sa.Column("cover_key", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="done"), _created(),
    )  # fmt: skip
    op.create_index(
        "ix_songs_user_created", "songs", ["tenant_id", "product_id", "user_id", "created_at"]
    )
    op.create_table(
        "speeches", sa.Column("id", sa.Uuid, primary_key=True), *_owner(),
        sa.Column("text", sa.Text, nullable=False), sa.Column("language", sa.Text, nullable=False),
        sa.Column("gender", sa.Text, nullable=False), sa.Column("voice", sa.Text, nullable=False),
        sa.Column("characters", sa.Integer, nullable=False),
        sa.Column("seconds", sa.Float, nullable=False),
        sa.Column("audio_key", sa.Text, nullable=False), _created(),
    )  # fmt: skip
    op.create_index(
        "ix_speeches_user_created", "speeches", ["tenant_id", "product_id", "user_id", "created_at"]
    )
    op.create_table(
        "transcripts", sa.Column("id", sa.Uuid, primary_key=True), *_owner(),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("language", sa.Text, nullable=False, server_default=""),
        sa.Column("engine", sa.Text, nullable=False, server_default=""),
        sa.Column("seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("segments", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text), _created(),
    )  # fmt: skip
    op.create_index(
        "ix_transcripts_owner_created", "transcripts", ["tenant_id", "user_id", "created_at"]
    )
    op.create_table(
        "lipsyncs", sa.Column("id", sa.Uuid, primary_key=True), *_owner(),
        sa.Column("source", sa.Text, nullable=False), sa.Column("status", sa.Text, nullable=False),
        sa.Column("script", sa.Text, nullable=False, server_default=""),
        sa.Column("style", sa.Text, nullable=False, server_default=""),
        sa.Column("transcript", sa.Text, nullable=False, server_default=""),
        sa.Column("seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("width", sa.Integer), sa.Column("height", sa.Integer),
        sa.Column("video_key", sa.Text), sa.Column("poster_key", sa.Text),
        sa.Column("error", sa.Text), _created(),
    )  # fmt: skip
    op.create_index(
        "ix_lipsyncs_user_created", "lipsyncs", ["tenant_id", "product_id", "user_id", "created_at"]
    )
