"""the MCP server's connections and their activity log (ADR-0069, stage M1)

One row per connection a person allowed (secret hashed, scopes, approval setting, folders) and one
per call at the endpoint (no content). The desktop profile's SQLite file gets the same tables on
first use.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column("scopes", sa.Text, nullable=False),
        sa.Column("policy", sa.Text, nullable=False),
        sa.Column("read_folders", sa.Text, nullable=False),
        sa.Column("write_folders", sa.Text, nullable=False),
        sa.Column("rate_per_minute", sa.Integer, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mcp_connections_user", "mcp_connections", ["tenant_id", "user_id"])
    op.create_table(
        "mcp_activity",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("connection_id", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("tool", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_activity_connection", "mcp_activity", ["connection_id", "created_at"])


def downgrade() -> None:
    op.drop_table("mcp_activity")
    op.drop_table("mcp_connections")
