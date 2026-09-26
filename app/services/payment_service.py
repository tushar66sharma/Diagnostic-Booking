"""Payments and the payment webhook.

Concurrency rule: every code path that changes a booking or its payments first locks the
booking row (SELECT ... FOR UPDATE). Locking in the same order everywhere means concurrent
requests for the same booking run one after another and cannot deadlock.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.schemas.payments import WebhookIn
from app.services.booking_service import get_user_booking
from app.services.payment_provider import MockPaymentProvider, SimulatedOutcome
from app.state_machine import transition

logger = logging.getLogger(__name__)

PAYABLE_STATUSES = (BookingStatus.PENDING, BookingStatus.FAILED)


def create_payment(
    db: Session,
    user: User,
    booking_id: int,
    provider: MockPaymentProvider,
    outcome: SimulatedOutcome | None = None,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    """Charge the booking's amount. Returns (payment, created); created is False when an
    earlier request with the same Idempotency-Key is being replayed."""
    booking = get_user_booking(db, user, booking_id, for_update=True)

    if idempotency_key:
        # Checked after taking the booking lock, so a concurrent retry with the same key
        # waits for the first request to commit and then sees its payment.
        previous = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if previous is not None:
            if previous.booking_id != booking.id:
                raise ConflictError("Idempotency-Key was already used for a different request")
            db.rollback()
            return previous, False

    if booking.status not in PAYABLE_STATUSES:
        raise ConflictError(f"Booking is {booking.status.value}; it cannot be paid")
    if booking.appointment_at <= datetime.now(timezone.utc):
        raise ConflictError("Appointment time has passed")
    if any(p.status == PaymentStatus.PENDING for p in booking.payments):
        raise ConflictError("A payment for this booking is already in progress")

    result = provider.charge(booking.amount, outcome)
    payment = Payment(
        booking=booking,
        amount=booking.amount,
        status=PaymentStatus.PENDING,
        provider_ref=result.provider_ref,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    if result.status != PaymentStatus.PENDING:
        apply_payment_result(payment, result.status)
    try:
        db.commit()
    except IntegrityError:  # unique constraints are the last line of defence
        db.rollback()
        raise ConflictError("Payment conflicts with an existing payment, please retry")

    logger.info(
        "payment.created",
        extra={"payment_id": payment.id, "booking_id": booking.id, "status": payment.status.value},
    )
    return payment, True


def apply_payment_result(payment: Payment, new_status: PaymentStatus) -> str:
    """Move a payment to SUCCESS/FAILED and update its booking. The caller must hold the booking lock.

    Payment SUCCESS/FAILED are final: a later, contradicting update is ignored (and logged for
    reconciliation) instead of flipping a confirmed booking back and forth.
    """
    if payment.status == new_status:
        return "already_applied"
    if payment.status != PaymentStatus.PENDING:
        logger.warning(
            "payment.conflicting_update_ignored",
            extra={"payment_id": payment.id, "current": payment.status.value, "received": new_status.value},
        )
        return "ignored_conflict"

    payment.status = new_status
    booking = payment.booking

    if new_status == PaymentStatus.SUCCESS:
        if booking.status in PAYABLE_STATUSES:
            transition(booking, BookingStatus.CONFIRMED)
        else:
            # Money arrived for a booking that was cancelled (or already paid) meanwhile.
            payment.refund_required = True
            logger.warning("payment.refund_required", extra={"payment_id": payment.id, "booking_id": booking.id})
    elif booking.status == BookingStatus.PENDING:
        transition(booking, BookingStatus.FAILED)
    return "applied"


def process_webhook(db: Session, event: WebhookIn) -> tuple[str, Payment | None]:
    """Apply a provider event exactly once, however many times it is delivered.

    1. Insert the event id. If it already exists, this is a redelivery: do nothing.
       (A concurrent redelivery blocks on the unique index until the first commits.)
    2. Lock the booking, apply the status, record the outcome, commit - all in one transaction.
       If anything fails, the event row is rolled back too, so the provider's retry is processed.
    """
    inserted_id = db.scalar(
        insert(WebhookEvent)
        .values(event_id=event.event_id, provider_ref=event.provider_ref, payload=event.model_dump())
        .on_conflict_do_nothing(index_elements=[WebhookEvent.event_id])
        .returning(WebhookEvent.id)
    )
    if inserted_id is None:
        db.rollback()
        logger.info("webhook.duplicate", extra={"event_id": event.event_id})
        return "duplicate", db.scalar(select(Payment).where(Payment.provider_ref == event.provider_ref))

    booking_id = db.scalar(select(Payment.booking_id).where(Payment.provider_ref == event.provider_ref))
    if booking_id is None:
        db.rollback()
        raise NotFoundError("Unknown payment reference")

    db.execute(select(Booking.id).where(Booking.id == booking_id).with_for_update())
    payment = db.scalar(
        select(Payment).where(Payment.provider_ref == event.provider_ref).execution_options(populate_existing=True)
    )
    result = apply_payment_result(payment, PaymentStatus(event.status))
    db.get(WebhookEvent, inserted_id).result = result
    db.commit()

    logger.info(
        "webhook.processed",
        extra={"event_id": event.event_id, "payment_id": payment.id, "result": result, "status": event.status},
    )
    return result, payment
