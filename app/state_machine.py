from app.errors import ConflictError
from app.models import Booking, BookingStatus

# The only booking status changes the system allows. Everything else is rejected.
#
#   PENDING --payment ok--> CONFIRMED --cancel--> CANCELLED
#      |  \--payment failed--> FAILED --retry ok--> CONFIRMED
#      \--cancel--> CANCELLED   FAILED --cancel--> CANCELLED
ALLOWED_TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    BookingStatus.PENDING: frozenset({BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED}),
    BookingStatus.FAILED: frozenset({BookingStatus.CONFIRMED, BookingStatus.CANCELLED}),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    BookingStatus.CANCELLED: frozenset(),
}


def can_transition(current: BookingStatus, target: BookingStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition(booking: Booking, target: BookingStatus) -> None:
    if not can_transition(booking.status, target):
        raise ConflictError(f"Booking cannot move from {booking.status.value} to {target.value}")
    booking.status = target
