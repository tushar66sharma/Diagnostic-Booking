import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import WebhookEvent
from app.schemas.payments import WebhookIn
from app.security import sign_webhook_payload
from app.services import payment_service
from tests.conftest import auth_headers
from tests.test_bookings import create_booking
from tests.test_payments import get_booking, pay


def send_webhook(client, event_id, provider_ref, status, signature=None):
    body = json.dumps({"event_id": event_id, "provider_ref": provider_ref, "status": status}).encode()
    headers = {"Content-Type": "application/json", "X-Signature": signature or sign_webhook_payload(body)}
    return client.post("/payments/webhook/", content=body, headers=headers)


@pytest.fixture
def booking(client, user, offering):
    return create_booking(client, user, offering)


@pytest.fixture
def pending_payment(client, user, booking):
    return pay(client, user, booking["id"], "pending").json()


def test_success_webhook_confirms_booking(client, user, booking, pending_payment):
    res = send_webhook(client, "evt_1", pending_payment["provider_ref"], "SUCCESS")

    assert res.status_code == 200
    assert res.json() == {
        "event_id": "evt_1", "result": "applied", "payment_status": "SUCCESS", "booking_status": "CONFIRMED"
    }
    assert get_booking(client, user, booking["id"])["status"] == "CONFIRMED"


def test_failed_webhook_fails_booking(client, user, booking, pending_payment):
    send_webhook(client, "evt_1", pending_payment["provider_ref"], "FAILED")

    assert get_booking(client, user, booking["id"])["status"] == "FAILED"


def test_repeated_event_is_processed_once(client, db, user, booking, pending_payment):
    ref = pending_payment["provider_ref"]

    first = send_webhook(client, "evt_1", ref, "SUCCESS")
    second = send_webhook(client, "evt_1", ref, "SUCCESS")
    third = send_webhook(client, "evt_1", ref, "SUCCESS")

    assert first.json()["result"] == "applied"
    assert second.status_code == third.status_code == 200  # 200 so the provider stops retrying
    assert second.json()["result"] == third.json()["result"] == "duplicate"
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    assert len(get_booking(client, user, booking["id"])["payments"]) == 1


def test_different_event_with_same_status_is_harmless(client, pending_payment):
    send_webhook(client, "evt_1", pending_payment["provider_ref"], "SUCCESS")

    res = send_webhook(client, "evt_2", pending_payment["provider_ref"], "SUCCESS")
    assert res.json()["result"] == "already_applied"


def test_late_failure_does_not_downgrade_confirmed_booking(client, user, booking, pending_payment):
    send_webhook(client, "evt_1", pending_payment["provider_ref"], "SUCCESS")

    res = send_webhook(client, "evt_2", pending_payment["provider_ref"], "FAILED")

    assert res.json()["result"] == "ignored_conflict"
    assert res.json()["payment_status"] == "SUCCESS"
    assert get_booking(client, user, booking["id"])["status"] == "CONFIRMED"


def test_success_for_cancelled_booking_flags_refund(client, user, booking, pending_payment):
    client.post(f"/bookings/{booking['id']}/cancel/", headers=auth_headers(user))

    res = send_webhook(client, "evt_1", pending_payment["provider_ref"], "SUCCESS")

    assert res.json()["booking_status"] == "CANCELLED"
    detail = get_booking(client, user, booking["id"])
    assert detail["status"] == "CANCELLED"
    assert detail["payments"][0]["refund_required"] is True


def test_webhook_for_instant_payment_is_accepted_idempotently(client, user, booking):
    """Providers often also send a webhook for payments we already resolved synchronously."""
    payment = pay(client, user, booking["id"], "success").json()

    res = send_webhook(client, "evt_1", payment["provider_ref"], "SUCCESS")
    assert res.json()["result"] == "already_applied"


def test_unknown_payment_reference_is_404_and_not_recorded(client, db):
    res = send_webhook(client, "evt_1", "sim_does_not_exist", "SUCCESS")

    assert res.status_code == 404
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 0


@pytest.mark.parametrize("signature", ["", "deadbeef"])
def test_bad_signature_is_rejected_without_side_effects(client, user, booking, pending_payment, signature):
    body = json.dumps({"event_id": "evt_1", "provider_ref": pending_payment["provider_ref"], "status": "SUCCESS"})
    res = client.post(
        "/payments/webhook/", content=body, headers={"Content-Type": "application/json", "X-Signature": signature}
    )

    assert res.status_code == 401
    assert get_booking(client, user, booking["id"])["status"] == "PENDING"


def test_missing_signature_is_rejected(client):
    assert client.post("/payments/webhook/", json={"event_id": "e"}).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"event_id": "e1", "provider_ref": "sim_x", "status": "REFUNDED"}',
        b'{"event_id": "", "provider_ref": "sim_x", "status": "SUCCESS"}',
        b'{"provider_ref": "sim_x", "status": "SUCCESS"}',
    ],
)
def test_malformed_event_is_422(client, payload):
    res = client.post("/payments/webhook/", content=payload, headers={"X-Signature": sign_webhook_payload(payload)})
    assert res.status_code == 422
    assert all(e["loc"][0] == "body" and "url" not in e for e in res.json()["detail"])


def test_concurrent_deliveries_of_same_event_apply_once(db, pending_payment):
    event = WebhookIn(event_id="evt_race", provider_ref=pending_payment["provider_ref"], status="SUCCESS")

    def deliver():
        with SessionLocal() as session:
            return payment_service.process_webhook(session, event)[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: deliver(), range(8)))

    assert sorted(results) == ["applied"] + ["duplicate"] * 7
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 1


def test_concurrent_conflicting_events_leave_consistent_state(client, user, booking, pending_payment):
    ref = pending_payment["provider_ref"]
    events = [WebhookIn(event_id=f"evt_{i}", provider_ref=ref, status=s)
              for i, s in enumerate(["SUCCESS", "FAILED"] * 4)]

    def deliver(event):
        with SessionLocal() as session:
            return payment_service.process_webhook(session, event)[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(deliver, events))

    assert results.count("applied") == 1
    detail = get_booking(client, user, booking["id"])
    payment_status = detail["payments"][0]["status"]
    assert (payment_status, detail["status"]) in {("SUCCESS", "CONFIRMED"), ("FAILED", "FAILED")}
