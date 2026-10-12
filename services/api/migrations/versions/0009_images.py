"""images: finished images of the wasifyai-image product (ADR-0036)

Product tables live in the shared database and carry tenant_id and product_id like every other
table (rule 7). The files are in object storage; the row holds their keys, relative to the user's
prefix.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text),
        sa.Column("run_id", sa.Text),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("image_key", sa.Text, nullable=False),
        sa.Column("thumb_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_images_user_created", "images", ["tenant_id", "product_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("images")
