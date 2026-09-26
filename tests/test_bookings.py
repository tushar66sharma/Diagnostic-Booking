from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models import Booking, BookingStatus, Payment, PaymentStatus
from tests.conftest import auth_headers, make_offering


def future(days=3) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def booking_payload(offering, **overrides):
    return {"centre_id": offering.centre_id, "test_id": offering.test_id, "appointment_at": future(), **overrides}


def create_booking(client, user, offering, **overrides):
    res = client.post("/bookings/", json=booking_payload(offering, **overrides), headers=auth_headers(user))
    assert res.status_code == 201, res.text
    return res.json()


def test_create_booking_snapshots_price_and_starts_pending(client, user, offering):
    booking = create_booking(client, user, offering)

    assert booking["status"] == "PENDING"
    assert booking["amount"] == "500.00"
    assert booking["user_id"] == user.id
    assert booking["centre_name"] == "City Diagnostics"
    assert booking["test_name"] == "Complete Blood Count"
    assert booking["payments"] == []


def test_later_price_change_does_not_affect_existing_booking(client, db, admin, user, offering):
    booking = create_booking(client, user, offering)
    client.put(
        f"/centres/{offering.centre_id}/tests/{offering.test_id}/", json={"price": "999"}, headers=auth_headers(admin)
    )

    res = client.get(f"/bookings/{booking['id']}/", headers=auth_headers(user))
    assert res.json()["amount"] == "500.00"


def test_booking_requires_authentication(client, offering):
    assert client.post("/bookings/", json=booking_payload(offering)).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"appointment_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
        {"appointment_at": "2030-01-01T10:00:00"},  # no timezone
        {"appointment_at": "not-a-date"},
        {"centre_id": "abc"},
    ],
    ids=["past", "naive", "garbage", "bad-id"],
)
def test_create_booking_validates_input(client, user, offering, overrides):
    res = client.post("/bookings/", json=booking_payload(offering, **overrides), headers=auth_headers(user))
    assert res.status_code == 422


def test_booking_a_test_the_centre_does_not_offer_is_404(client, db, user, offering):
    other = make_offering(db, centre_name="Other Centre", test_name="MRI Brain")

    # MRI exists, but not at City Diagnostics
    res = client.post(
        "/bookings/", json=booking_payload(offering, test_id=other.test_id), headers=auth_headers(user)
    )
    assert res.status_code == 404


def test_booking_an_inactive_offering_is_404(client, db, user, offering):
    offering.is_active = False
    db.commit()

    res = client.post("/bookings/", json=booking_payload(offering), headers=auth_headers(user))
    assert res.status_code == 404


def test_duplicate_active_booking_for_same_slot_conflicts(client, user, offering):
    slot = future()
    create_booking(client, user, offering, appointment_at=slot)

    res = client.post("/bookings/", json=booking_payload(offering, appointment_at=slot), headers=auth_headers(user))
    assert res.status_code == 409


def test_same_slot_can_be_rebooked_after_cancelling(client, user, offering):
    slot = future()
    first = create_booking(client, user, offering, appointment_at=slot)
    client.post(f"/bookings/{first['id']}/cancel/", headers=auth_headers(user))

    create_booking(client, user, offering, appointment_at=slot)


def test_list_bookings_only_shows_own_and_filters_by_status(client, user, other_user, offering):
    mine = create_booking(client, user, offering, appointment_at=future(1))
    create_booking(client, user, offering, appointment_at=future(2))
    create_booking(client, other_user, offering)
    client.post(f"/bookings/{mine['id']}/cancel/", headers=auth_headers(user))

    all_mine = client.get("/bookings/", headers=auth_headers(user)).json()
    cancelled = client.get("/bookings/", params={"status": "CANCELLED"}, headers=auth_headers(user)).json()

    assert all_mine["total"] == 2
    assert {b["user_id"] for b in all_mine["items"]} == {user.id}
    assert [b["id"] for b in cancelled["items"]] == [mine["id"]]


def test_cannot_read_or_cancel_someone_elses_booking(client, user, other_user, offering):
    booking = create_booking(client, user, offering)
    h = auth_headers(other_user)

    # 404, not 403: do not reveal that the booking exists
    assert client.get(f"/bookings/{booking['id']}/", headers=h).status_code == 404
    assert client.post(f"/bookings/{booking['id']}/cancel/", headers=h).status_code == 404
    assert client.get(f"/bookings/{booking['id']}/", headers=auth_headers(user)).json()["status"] == "PENDING"


@pytest.mark.parametrize("booking_id", ["999", "abc"])
def test_invalid_booking_id(client, user, booking_id):
    res = client.get(f"/bookings/{booking_id}/", headers=auth_headers(user))
    assert res.status_code == (404 if booking_id.isdigit() else 422)


def test_cancel_is_idempotent(client, user, offering):
    booking = create_booking(client, user, offering)
    h = auth_headers(user)

    first = client.post(f"/bookings/{booking['id']}/cancel/", headers=h)
    second = client.post(f"/bookings/{booking['id']}/cancel/", headers=h)

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "CANCELLED"


def test_cannot_cancel_after_appointment_time(client, db, user, offering):
    booking = create_booking(client, user, offering)
    db.execute(
        update(Booking)
        .where(Booking.id == booking["id"])
        .values(appointment_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    db.commit()

    res = client.post(f"/bookings/{booking['id']}/cancel/", headers=auth_headers(user))
    assert res.status_code == 409


def test_cancelling_confirmed_booking_flags_payment_for_refund(client, db, user, offering):
    booking = create_booking(client, user, offering)
    db.add(Payment(booking_id=booking["id"], amount=500, status=PaymentStatus.SUCCESS, provider_ref="sim_x"))
    db.execute(update(Booking).where(Booking.id == booking["id"]).values(status=BookingStatus.CONFIRMED))
    db.commit()

    res = client.post(f"/bookings/{booking['id']}/cancel/", headers=auth_headers(user))

    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"
    assert res.json()["payments"][0]["refund_required"] is True
