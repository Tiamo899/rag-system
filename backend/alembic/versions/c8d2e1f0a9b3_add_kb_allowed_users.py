"""知识库受限范围支持指定用户：allowed_users（存用户 UUID 字符串）。

兼容性：存量知识库默认为空数组，行为不变。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c8d2e1f0a9b3"
down_revision = "b7c1d9e4f2a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "allowed_users",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "allowed_users")
