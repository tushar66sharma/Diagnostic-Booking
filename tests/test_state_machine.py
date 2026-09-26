import pytest

from app.errors import ConflictError
from app.models import Booking, BookingStatus as S
from app.state_machine import can_transition, transition

ALLOWED = {
    (S.PENDING, S.CONFIRMED),
    (S.PENDING, S.FAILED),
    (S.PENDING, S.CANCELLED),
    (S.FAILED, S.CONFIRMED),
    (S.FAILED, S.CANCELLED),
    (S.CONFIRMED, S.CANCELLED),
}


@pytest.mark.parametrize("current", list(S))
@pytest.mark.parametrize("target", list(S))
def test_transition_table(current, target):
    assert can_transition(current, target) == ((current, target) in ALLOWED)


def test_cancelled_is_terminal():
    booking = Booking(status=S.CANCELLED)

    with pytest.raises(ConflictError):
        transition(booking, S.CONFIRMED)
    assert booking.status == S.CANCELLED


def test_confirmed_cannot_be_downgraded_to_failed():
    booking = Booking(status=S.CONFIRMED)

    with pytest.raises(ConflictError):
        transition(booking, S.FAILED)
