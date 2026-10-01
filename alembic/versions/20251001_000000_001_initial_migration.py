"""Initial migration with documents, nodes, and images tables

Revision ID: 001
Revises:
Create Date: 2025-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # Create nodes table
    op.create_table(
        'nodes',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('node_type', sa.String(), nullable=False),
        sa.Column('heading', sa.String(), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('search_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['nodes.id'], ondelete='CASCADE'),
    )

    # Create indexes for nodes
    op.create_index('ix_nodes_document_id', 'nodes', ['document_id'])
    op.create_index('ix_nodes_parent_id', 'nodes', ['parent_id'])
    op.create_index('idx_nodes_type', 'nodes', ['node_type'])

    # Create images table
    op.create_table(
        'images',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('minio_key', sa.String(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='CASCADE'),
    )

    # Create indexes for images
    op.create_index('ix_images_document_id', 'images', ['document_id'])
    op.create_index('ix_images_node_id', 'images', ['node_id'])

    # Add pgvector extension and embedding column (using raw SQL for pgvector type)
    try:
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    except Exception:
        pass  # Extension might already exist
    try:
        op.execute("ALTER TABLE nodes ADD COLUMN IF NOT EXISTS embedding vector(384)")
    except Exception:
        pass  # Column might already exist
    try:
        op.execute("CREATE INDEX IF NOT EXISTS idx_nodes_embedding ON nodes USING ivfflat (embedding vector_cosine_ops)")
    except Exception:
        pass  # Index might already exist


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_nodes_embedding', table_name='nodes')
    op.drop_index('ix_images_node_id', table_name='images')
    op.drop_index('ix_images_document_id', table_name='images')
    op.drop_index('idx_nodes_type', table_name='nodes')
    op.drop_index('ix_nodes_parent_id', table_name='nodes')
    op.drop_index('ix_nodes_document_id', table_name='nodes')

    # Drop embedding column
    op.drop_column('nodes', 'embedding')

    # Drop tables
    op.drop_table('images')
    op.drop_table('nodes')
    op.drop_table('documents')

    # Optionally drop pgvector extension
    # op.execute('DROP EXTENSION IF EXISTS vector')
