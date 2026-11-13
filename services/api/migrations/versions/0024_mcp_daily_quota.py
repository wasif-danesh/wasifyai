"""a daily quota per MCP connection (ADR-0069 decision 10, stage M3)

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("calls_per_day", sa.Integer, nullable=False, server_default="1000"),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "calls_per_day")
