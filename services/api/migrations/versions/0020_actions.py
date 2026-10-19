"""actions: the audit log of the action catalogue and the approvals waiting for a person

ADR-0068. The audit log says who asked (`origin`), which action, how it ended and how long it took;
it holds no content. A pending approval holds the parameters the person is asked about until it is
decided, then they are dropped. On the desktop the same tables are created on first use by
`wasifyai_platform_sdk.actions.audit`.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "action_audit",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("action_id", sa.Text, nullable=False),
        sa.Column("origin", sa.Text, nullable=False),  # window | assistant | mcp:<connection>
        sa.Column("effect", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False, server_default=""),
        sa.Column("approval", sa.Text, nullable=False, server_default="none"),
        sa.Column("job_id", sa.Text),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        _created(),
    )
    op.create_index(
        "ix_action_audit_user_time", "action_audit", ["tenant_id", "user_id", "created_at"]
    )
    op.create_index("ix_action_audit_job", "action_audit", ["tenant_id", "user_id", "job_id"])
    op.create_table(
        "action_approvals",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("product_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("action_id", sa.Text, nullable=False),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column("params_hash", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("params", sa.Text),  # JSON while pending, NULL once decided
        sa.Column(
            "status", sa.Text, nullable=False
        ),  # pending | approved | denied | used | expired
        sa.Column("decided_by", sa.Text, nullable=False, server_default=""),
        _created(),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_action_approvals_user_status", "action_approvals", ["tenant_id", "user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_action_approvals_user_status", table_name="action_approvals")
    op.drop_table("action_approvals")
    op.drop_index("ix_action_audit_job", table_name="action_audit")
    op.drop_index("ix_action_audit_user_time", table_name="action_audit")
    op.drop_table("action_audit")
