from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import BookingStatus, PaymentStatus
from app.services.payment_provider import SimulatedOutcome


class PaymentIn(BaseModel):
    booking_id: int
    simulate: SimulatedOutcome | None = Field(
        default=None,
        description="Force the mock provider's answer. Omit for a random result "
        "(success with probability PAYMENT_SUCCESS_RATE). 'pending' waits for a webhook.",
    )


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider_ref: str
    refund_required: bool
    booking_status: BookingStatus
    created_at: datetime


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128, description="Unique per event; used for deduplication")
    provider_ref: str = Field(min_length=1, max_length=64)
    status: Literal["SUCCESS", "FAILED"]


class WebhookOut(BaseModel):
    event_id: str
    result: str = Field(description="applied | already_applied | ignored_conflict | duplicate")
    payment_status: PaymentStatus | None = None
    booking_status: BookingStatus | None = None
