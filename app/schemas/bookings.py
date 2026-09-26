from datetime import datetime, timezone
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from app.models import BookingStatus, PaymentStatus


class BookingIn(BaseModel):
    centre_id: int
    test_id: int
    appointment_at: AwareDatetime  # must carry a timezone, e.g. 2026-10-01T09:30:00+05:30

    @field_validator("appointment_at")
    @classmethod
    def must_be_in_future(cls, v: datetime) -> datetime:
        if v <= datetime.now(timezone.utc):
            raise ValueError("must be in the future")
        return v


class PaymentSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    status: PaymentStatus
    provider_ref: str
    refund_required: bool
    created_at: datetime


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    centre_id: int
    centre_name: str
    test_id: int
    test_name: str
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


class BookingDetailOut(BookingOut):
    payments: list[PaymentSummaryOut]
