import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError
from app.models import Booking, BookingStatus, CentreTest, PaymentStatus, User
from app.schemas.bookings import BookingIn
from app.schemas.common import PageParams
from app.state_machine import transition

logger = logging.getLogger(__name__)

_LOAD_RELATIONS = (selectinload(Booking.centre), selectinload(Booking.test), selectinload(Booking.payments))


def create_booking(db: Session, user: User, data: BookingIn) -> Booking:
    offering = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == data.centre_id, CentreTest.test_id == data.test_id, CentreTest.is_active
        )
    )
    if offering is None:
        raise NotFoundError("This test is not offered at this centre")

    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_at=data.appointment_at,
        amount=offering.price,  # price snapshot
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:  # uq_booking_active_slot
        db.rollback()
        raise ConflictError("You already have an active booking for this test at this centre and time")
    logger.info("booking.created", extra={"booking_id": booking.id, "user_id": user.id, "amount": str(booking.amount)})
    return get_user_booking(db, user, booking.id)


def get_user_booking(db: Session, user: User, booking_id: int, for_update: bool = False) -> Booking:
    """Fetch a booking owned by `user`. Someone else's booking is reported as not found, not forbidden,
    so the API does not reveal which booking ids exist."""
    query = select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id).options(*_LOAD_RELATIONS)
    if for_update:
        query = query.with_for_update(of=Booking)
    booking = db.scalar(query)
    if booking is None:
        raise NotFoundError("Booking not found")
    return booking


def list_user_bookings(
    db: Session, user: User, page: PageParams, status: BookingStatus | None = None
) -> tuple[list[Booking], int]:
    query = select(Booking).where(Booking.user_id == user.id)
    if status is not None:
        query = query.where(Booking.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(
        query.options(selectinload(Booking.centre), selectinload(Booking.test))
        .order_by(Booking.created_at.desc(), Booking.id.desc())
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    return list(items), total


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    booking = get_user_booking(db, user, booking_id, for_update=True)

    if booking.status == BookingStatus.CANCELLED:  # cancelling twice is a no-op, not an error
        db.rollback()
        return booking
    if booking.appointment_at <= datetime.now(timezone.utc):
        raise ConflictError("Cannot cancel a booking whose appointment time has passed")

    transition(booking, BookingStatus.CANCELLED)
    for payment in booking.payments:
        if payment.status == PaymentStatus.SUCCESS:
            payment.refund_required = True
    db.commit()
    logger.info("booking.cancelled", extra={"booking_id": booking.id, "user_id": user.id})
    return booking
