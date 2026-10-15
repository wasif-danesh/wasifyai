"""image recipes and favourites (stage B)

`recipe` is the JSON (as text) of what made the image: prompt, mode, size, seed. Old rows have none.
`favourite` marks the images the person wants to find first.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.add_column("images", sa.Column("recipe", sa.Text))
    op.add_column(
        "images", sa.Column("favourite", sa.Boolean, nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("images", "favourite")
    op.drop_column("images", "recipe")
