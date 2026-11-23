"""新增知识库可见范围：visibility + allowed_roles。

兼容性：存量知识库全部回填为 public，行为与升级前一致（所有登录用户可见）。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7c1d9e4f2a8"
down_revision = "a9c3e5f7b2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="public"),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "allowed_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "allowed_roles")
    op.drop_column("knowledge_bases", "visibility")
