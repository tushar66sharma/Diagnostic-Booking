"""initial schema

Revision ID: b5643dd1aa0f
Revises: 
Create Date: 2026-09-26 17:00:27.564544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b5643dd1aa0f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('centres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_centres_city'), 'centres', ['city'], unique=False)
    op.create_table('diagnostic_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('webhook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('provider_ref', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', sa.String(length=32), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    op.create_index(op.f('ix_webhook_events_provider_ref'), 'webhook_events', ['provider_ref'], unique=False)
    op.create_table('centre_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price > 0', name='ck_centre_test_price_positive'),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('centre_id', 'test_id', name='uq_centre_test')
    )
    op.create_index(op.f('ix_centre_tests_test_id'), 'centre_tests', ['test_id'], unique=False)
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('appointment_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED', name='booking_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_booking_amount_positive'),
    sa.ForeignKeyConstraint(['centre_id', 'test_id'], ['centre_tests.centre_id', 'centre_tests.test_id'], name='fk_booking_centre_test', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], ),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bookings_status'), 'bookings', ['status'], unique=False)
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)
    op.create_index('uq_booking_active_slot', 'bookings', ['user_id', 'centre_id', 'test_id', 'appointment_at'], unique=True, postgresql_where=sa.text("status IN ('PENDING', 'CONFIRMED')"))
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('booking_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'SUCCESS', 'FAILED', name='payment_status'), nullable=False),
    sa.Column('provider_ref', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('refund_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_payment_amount_positive'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key'),
    sa.UniqueConstraint('provider_ref')
    )
    op.create_index(op.f('ix_payments_booking_id'), 'payments', ['booking_id'], unique=False)
    op.create_index('uq_payment_in_flight', 'payments', ['booking_id'], unique=True, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('uq_payment_success', 'payments', ['booking_id'], unique=True, postgresql_where=sa.text("status = 'SUCCESS'"))


def downgrade() -> None:
    op.drop_index('uq_payment_success', table_name='payments', postgresql_where=sa.text("status = 'SUCCESS'"))
    op.drop_index('uq_payment_in_flight', table_name='payments', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index(op.f('ix_payments_booking_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index('uq_booking_active_slot', table_name='bookings', postgresql_where=sa.text("status IN ('PENDING', 'CONFIRMED')"))
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_status'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_index(op.f('ix_centre_tests_test_id'), table_name='centre_tests')
    op.drop_table('centre_tests')
    op.drop_index(op.f('ix_webhook_events_provider_ref'), table_name='webhook_events')
    op.drop_table('webhook_events')
    op.drop_table('users')
    op.drop_table('diagnostic_tests')
    op.drop_index(op.f('ix_centres_city'), table_name='centres')
    op.drop_table('centres')
    sa.Enum(name='payment_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='booking_status').drop(op.get_bind(), checkfirst=True)
