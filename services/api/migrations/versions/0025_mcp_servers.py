"""the MCP client's servers and their activity log (ADR-0070, stage C1)

One row per server the person added in Settings (no secret: values live in the secret store) and
one per call the assistant made (content only when the person keeps it). The desktop profile's
SQLite file gets the same tables on first use.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("transport", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False, server_default=""),
        sa.Column("command", sa.Text, nullable=False, server_default=""),
        sa.Column("args", sa.Text, nullable=False, server_default=""),
        sa.Column("env_names", sa.Text, nullable=False, server_default=""),
        sa.Column("has_token", sa.Integer, nullable=False, server_default="0"),
        sa.Column("trust", sa.Text, nullable=False, server_default="ask"),
        sa.Column("allowed_tools", sa.Text, nullable=False, server_default=""),
        sa.Column("timeout_s", sa.Integer, nullable=False, server_default="60"),
        sa.Column("keep_content", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes_received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_mcp_servers_user", "mcp_servers", ["tenant_id", "user_id"])
    op.create_table(
        "mcp_client_activity",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("server_id", sa.Text, nullable=False),
        sa.Column("tool", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes_received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_client_activity_server", "mcp_client_activity", ["server_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("mcp_client_activity")
    op.drop_table("mcp_servers")
