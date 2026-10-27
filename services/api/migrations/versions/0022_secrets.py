"""the secret store's table (stage F4 of the 2026-10-27 plan; ADR-0092)

One row per named secret (`hf.token`, `web.search.exa` ...), the value a Fernet token under
MEDIA_SECRETS_KEY. The desktop profile's SQLite file gets the same table on first use.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("secrets")
