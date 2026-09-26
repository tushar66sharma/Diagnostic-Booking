import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.errors import ConflictError
from app.main import app
from app.models import Booking, Payment
from app.services import payment_service
from app.services.payment_provider import MockPaymentProvider, get_payment_provider
from tests.conftest import auth_headers
from tests.test_bookings import create_booking


def pay(client, user, booking_id, simulate="success", key=None):
    headers = auth_headers(user)
    if key:
        headers["Idempotency-Key"] = key
    body = {"booking_id": booking_id}
    if simulate:
        body["simulate"] = simulate
    return client.post("/payments/", json=body, headers=headers)


def get_booking(client, user, booking_id):
    return client.get(f"/bookings/{booking_id}/", headers=auth_headers(user)).json()


@pytest.fixture
def booking(client, user, offering):
    return create_booking(client, user, offering)


def test_successful_payment_confirms_booking(client, user, booking):
    res = pay(client, user, booking["id"], "success")

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "SUCCESS"
    assert body["amount"] == "500.00"
    assert body["booking_status"] == "CONFIRMED"
    assert body["provider_ref"].startswith("sim_")


def test_failed_payment_marks_booking_failed_and_can_be_retried(client, user, booking):
    failed = pay(client, user, booking["id"], "failed").json()
    assert failed["status"] == "FAILED"
    assert failed["booking_status"] == "FAILED"

    retry = pay(client, user, booking["id"], "success").json()
    assert retry["booking_status"] == "CONFIRMED"

    detail = get_booking(client, user, booking["id"])
    assert [p["status"] for p in detail["payments"]] == ["FAILED", "SUCCESS"]


def test_pending_payment_leaves_booking_pending(client, user, booking):
    res = pay(client, user, booking["id"], "pending").json()

    assert res["status"] == "PENDING"
    assert res["booking_status"] == "PENDING"


def test_random_outcome_uses_provider(client, user, booking):
    app.dependency_overrides[get_payment_provider] = lambda: MockPaymentProvider(success_rate=0.0, rng=random.Random(1))
    try:
        res = pay(client, user, booking["id"], simulate=None)
    finally:
        app.dependency_overrides.clear()

    assert res.json()["status"] == "FAILED"


def test_cannot_pay_twice_for_confirmed_booking(client, user, booking):
    pay(client, user, booking["id"], "success")

    res = pay(client, user, booking["id"], "success")
    assert res.status_code == 409


def test_cannot_start_second_payment_while_one_is_in_flight(client, user, booking):
    pay(client, user, booking["id"], "pending")

    assert pay(client, user, booking["id"], "success").status_code == 409


def test_cannot_pay_for_cancelled_booking(client, user, booking):
    client.post(f"/bookings/{booking['id']}/cancel/", headers=auth_headers(user))

    assert pay(client, user, booking["id"]).status_code == 409


def test_cannot_pay_after_appointment_time(client, db, user, booking):
    db.execute(
        update(Booking)
        .where(Booking.id == booking["id"])
        .values(appointment_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    db.commit()

    assert pay(client, user, booking["id"]).status_code == 409


def test_cannot_pay_for_someone_elses_booking(client, other_user, booking):
    assert pay(client, other_user, booking["id"]).status_code == 404


@pytest.mark.parametrize("body", [{"booking_id": 999}, {"booking_id": "abc"}, {}, {"booking_id": 1, "simulate": "maybe"}])
def test_invalid_payment_requests(client, user, body):
    res = client.post("/payments/", json=body, headers=auth_headers(user))
    assert res.status_code == (404 if body.get("booking_id") == 999 else 422)


def test_payment_requires_authentication(client, booking):
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401


def test_idempotency_key_replays_original_payment(client, db, user, booking):
    first = pay(client, user, booking["id"], "failed", key="key-1")
    # A retry of the same request; even a different `simulate` must not create a new charge.
    second = pay(client, user, booking["id"], "success", key="key-1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "FAILED"
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_idempotency_key_reused_for_other_booking_conflicts(client, user, offering, booking):
    other = create_booking(client, user, offering, appointment_at=(datetime.now(timezone.utc) + timedelta(days=9)).isoformat())
    pay(client, user, booking["id"], "success", key="shared")

    assert pay(client, user, other["id"], "success", key="shared").status_code == 409


def run_concurrently(fn, n=5):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: fn(), range(n)))


def test_concurrent_payments_for_same_booking_charge_once(db, user, booking):
    def attempt():
        with SessionLocal() as session:
            me = session.merge(user)
            try:
                payment_service.create_payment(session, me, booking["id"], MockPaymentProvider(), "success")
                return "created"
            except ConflictError:
                return "conflict"

    results = run_concurrently(attempt)

    assert sorted(results) == ["conflict"] * 4 + ["created"]
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_concurrent_retries_with_same_idempotency_key_charge_once(db, user, booking):
    def attempt():
        with SessionLocal() as session:
            me = session.merge(user)
            payment, created = payment_service.create_payment(
                session, me, booking["id"], MockPaymentProvider(), "success", idempotency_key="same-key"
            )
            return payment.id, created

    results = run_concurrently(attempt)

    assert len({pid for pid, _ in results}) == 1
    assert sum(created for _, created in results) == 1
