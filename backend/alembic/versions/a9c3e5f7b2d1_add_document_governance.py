# backend/alembic/versions/a9c3e5f7b2d1_add_document_governance.py
"""add document governance columns

Revision ID: a9c3e5f7b2d1
Revises: e23b6db22acb
Create Date: 2026-10-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'a9c3e5f7b2d1'
down_revision = 'e23b6db22acb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('valid_from', sa.Date(), nullable=True))
    op.add_column('documents', sa.Column('valid_to', sa.Date(), nullable=True))
    op.add_column('documents', sa.Column('version_no', sa.String(length=50), nullable=True))
    op.add_column('documents', sa.Column('superseded_by', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('supersedes_doc_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_documents_superseded_by', 'documents', 'documents',
        ['superseded_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_documents_supersedes_doc_id', 'documents', 'documents',
        ['supersedes_doc_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_documents_supersedes_doc_id', 'documents', type_='foreignkey')
    op.drop_constraint('fk_documents_superseded_by', 'documents', type_='foreignkey')
    op.drop_column('documents', 'supersedes_doc_id')
    op.drop_column('documents', 'superseded_by')
    op.drop_column('documents', 'version_no')
    op.drop_column('documents', 'valid_to')
    op.drop_column('documents', 'valid_from')
