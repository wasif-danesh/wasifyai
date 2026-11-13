"""what a picture or a clip was made from (ADR-0093, stage U8)

`source_id` on `images` is the picture of the library an Edit, Inpaint or Reference started from;
on `videos` it is the clip an Extend carries on or the picture an Animate sets moving. Both are
null for things made from words or from a file the person added, and for rows from before this.
The indexes answer "what was made from this one" for the Library's detail view. The desktop
profile's SQLite file gets the same column on first use.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    for table in ("images", "videos"):
        op.add_column(table, sa.Column("source_id", sa.Uuid))
        op.create_index(f"ix_{table}_source", table, ["tenant_id", "user_id", "source_id"])


def downgrade() -> None:
    for table in ("videos", "images"):
        op.drop_index(f"ix_{table}_source", table_name=table)
        op.drop_column(table, "source_id")
