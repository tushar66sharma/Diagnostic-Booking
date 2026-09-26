"""A stand-in for a real payment gateway (Razorpay, Stripe, ...)."""

import random
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.config import settings
from app.models import PaymentStatus

# success / failed: the provider answers immediately.
# pending: the provider accepts the charge and reports the result later via the webhook.
SimulatedOutcome = Literal["success", "failed", "pending"]


@dataclass(frozen=True)
class ChargeResult:
    provider_ref: str
    status: PaymentStatus


class MockPaymentProvider:
    def __init__(self, success_rate: float = settings.payment_success_rate, rng: random.Random | None = None):
        self.success_rate = success_rate
        self.rng = rng or random.Random()

    def charge(self, amount: Decimal, outcome: SimulatedOutcome | None = None) -> ChargeResult:
        if outcome is None:
            outcome = "success" if self.rng.random() < self.success_rate else "failed"
        status = {
            "success": PaymentStatus.SUCCESS,
            "failed": PaymentStatus.FAILED,
            "pending": PaymentStatus.PENDING,
        }[outcome]
        return ChargeResult(provider_ref=f"sim_{uuid.uuid4().hex}", status=status)


def get_payment_provider() -> MockPaymentProvider:
    """FastAPI dependency, so tests (or a real gateway) can be swapped in."""
    return MockPaymentProvider()
