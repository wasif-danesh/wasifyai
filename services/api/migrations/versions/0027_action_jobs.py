"""long action jobs that outlive a restart (stage J3 of the 2026-10-27 plan)

One row per long job the action executor runs (`job.status`, `job.wait` and `job.cancel` follow
it): who started it and from where, its status and progress, the product run it started (so a
restarted engine can read how it ended), the action's parameters (to read its result from that
run) and its result once it has ended. Times are seconds since the epoch. The desktop profile's
SQLite file gets the same table on first use.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    op.create_table(
        "action_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("action_id", sa.Text, nullable=False),
        sa.Column("origin", sa.Text, nullable=False),  # window | assistant | mcp:<connection>
        sa.Column("cancellable", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False),  # running | ok | refused | error | cancelled
        sa.Column("run_id", sa.Text),
        sa.Column("params", sa.Text),  # JSON
        sa.Column("progress", sa.Text),  # JSON
        sa.Column("result", sa.Text),  # JSON, once it has ended
        sa.Column("started_at", sa.Float, nullable=False),
        sa.Column("ended_at", sa.Float),
    )
    op.create_index("ix_action_jobs_user", "action_jobs", ["tenant_id", "user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_action_jobs_user", table_name="action_jobs")
    op.drop_table("action_jobs")
