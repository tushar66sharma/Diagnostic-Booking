import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(10, 2)


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


class Centre(TimestampMixin, Base):
    __tablename__ = "centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(Text)

    offerings: Mapped[list["CentreTest"]] = relationship(back_populates="centre")


class DiagnosticTest(TimestampMixin, Base):
    """Catalogue entry (e.g. "Complete Blood Count"). Price is per centre, see CentreTest."""

    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class CentreTest(TimestampMixin, Base):
    """A test offered by a centre, at that centre price."""

    __tablename__ = "centre_tests"
    __table_args__ = (
        UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),
        CheckConstraint("price > 0", name="ck_centre_test_price_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id", ondelete="CASCADE"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id", ondelete="RESTRICT"), index=True)
    price: Mapped[Decimal] = mapped_column(Money)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    centre: Mapped[Centre] = relationship(back_populates="offerings")
    test: Mapped[DiagnosticTest] = relationship()


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["centre_id", "test_id"],
            ["centre_tests.centre_id", "centre_tests.test_id"],
            name="fk_booking_centre_test",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="ck_booking_amount_positive"),
        Index(
            "uq_booking_active_slot",
            "user_id", "centre_id", "test_id", "appointment_at",
            unique=True,
            postgresql_where=text("status IN (''PENDING'', ''CONFIRMED'')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"), default=BookingStatus.PENDING, index=True
    )

    user: Mapped[User] = relationship()
    centre: Mapped[Centre] = relationship()
    test: Mapped[DiagnosticTest] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="booking", order_by="Payment.id")

    @property
    def centre_name(self) -> str:
        return self.centre.name

    @property
    def test_name(self) -> str:
        return self.test.name


class Payment(TimestampMixin, Base):
    """One attempt to pay for a booking. A booking may have several (e.g. failed, then retried)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index("uq_payment_in_flight", "booking_id", unique=True, postgresql_where=text("status = ''PENDING''")),
        Index("uq_payment_success", "booking_id", unique=True, postgresql_where=text("status = ''SUCCESS''")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING
    )
    provider_ref: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    refund_required: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    booking: Mapped[Booking] = relationship(back_populates="payments")

    @property
    def booking_status(self) -> BookingStatus:
        return self.booking.status
