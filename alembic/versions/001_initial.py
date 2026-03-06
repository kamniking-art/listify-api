"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=True, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=True),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('country', sa.String(10), nullable=False, server_default='RU'),
        sa.Column('currency', sa.String(10), nullable=False, server_default='RUB'),
        sa.Column('is_anonymous', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('device_id', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_device_id', 'users', ['device_id'])

    op.create_table('shopping_lists',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('emoji', sa.String(10), nullable=False, server_default='🛒'),
        sa.Column('accent_color', sa.String(20), nullable=False, server_default='#6c63ff'),
        sa.Column('budget', sa.Float, nullable=True),
        sa.Column('is_shared', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_archived', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('store_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_shopping_lists_user_id', 'shopping_lists', ['user_id'])

    op.execute("CREATE TYPE item_status AS ENUM ('planned','in_cart','bought','not_found')")

    op.create_table('shopping_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('list_id', sa.String(36), sa.ForeignKey('shopping_lists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name_raw', sa.String(255), nullable=False),
        sa.Column('product_id', sa.String(36), nullable=True),
        sa.Column('qty', sa.Float, nullable=False, server_default='1.0'),
        sa.Column('unit', sa.String(30), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('status', sa.Enum('planned','in_cart','bought','not_found', name='item_status'), nullable=False, server_default='planned'),
        sa.Column('note', sa.Text, nullable=True),
        sa.Column('estimated_price', sa.Float, nullable=True),
        sa.Column('position', sa.Integer, nullable=False, server_default='0'),
        sa.Column('added_by', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_shopping_items_list_id', 'shopping_items', ['list_id'])
    op.create_index('ix_shopping_items_status', 'shopping_items', ['status'])

    op.execute("CREATE TYPE receipt_status AS ENUM ('uploaded','processing','parsed','matched','confirmed','error')")

    op.create_table('receipts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('store_id', sa.String(36), nullable=True),
        sa.Column('store_raw', sa.String(200), nullable=True),
        sa.Column('receipt_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total', sa.Float, nullable=True),
        sa.Column('currency', sa.String(10), nullable=False, server_default='RUB'),
        sa.Column('status', sa.Enum('uploaded','processing','parsed','matched','confirmed','error', name='receipt_status'), nullable=False, server_default='uploaded'),
        sa.Column('confidence', sa.Float, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_receipts_user_id', 'receipts', ['user_id'])

    op.create_table('receipt_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('receipt_id', sa.String(36), sa.ForeignKey('receipts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name_raw', sa.String(255), nullable=False),
        sa.Column('normalized_name', sa.String(255), nullable=True),
        sa.Column('qty', sa.Float, nullable=True),
        sa.Column('unit_price', sa.Float, nullable=True),
        sa.Column('line_total', sa.Float, nullable=True),
        sa.Column('matched_item_id', sa.String(36), nullable=True),
        sa.Column('match_confidence', sa.Float, nullable=True),
    )
    op.create_index('ix_receipt_items_receipt_id', 'receipt_items', ['receipt_id'])

    op.create_table('price_points',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('product_id', sa.String(36), nullable=True),
        sa.Column('name_normalized', sa.String(255), nullable=False),
        sa.Column('store_id', sa.String(36), nullable=True),
        sa.Column('store_raw', sa.String(200), nullable=True),
        sa.Column('price', sa.Float, nullable=False),
        sa.Column('currency', sa.String(10), nullable=False, server_default='RUB'),
        sa.Column('country', sa.String(10), nullable=False, server_default='RU'),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_price_points_name', 'price_points', ['name_normalized'])
    op.create_index('ix_price_points_store', 'price_points', ['store_raw'])
    op.create_index('ix_price_points_recorded_at', 'price_points', ['recorded_at'])


def downgrade():
    op.drop_table('price_points')
    op.drop_table('receipt_items')
    op.drop_table('receipts')
    op.drop_table('shopping_items')
    op.drop_table('shopping_lists')
    op.drop_table('users')
    op.execute("DROP TYPE IF EXISTS item_status")
    op.execute("DROP TYPE IF EXISTS receipt_status")
