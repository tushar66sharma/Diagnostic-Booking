from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import AuthenticationError
from app.models import User
from app.schemas.common import error_responses
from app.schemas.payments import PaymentIn, PaymentOut, WebhookIn, WebhookOut
from app.security import verify_webhook_signature
from app.services import payment_service
from app.services.payment_provider import MockPaymentProvider, get_payment_provider

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": PaymentOut, "description": "Replay of an earlier request with the same Idempotency-Key"},
        **error_responses(
            401, 404, 409,
            _409="Booking not payable (confirmed, cancelled, past, payment in progress) "
            "or Idempotency-Key reused for another booking",
        ),
    },
)
def create_payment(
    body: PaymentIn,
    response: Response,
    idempotency_key: str | None = Header(
        None, max_length=128, description="Retrying with the same key returns the original payment"
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    provider: MockPaymentProvider = Depends(get_payment_provider),
):
    payment, created = payment_service.create_payment(
        db, user, body.booking_id, provider, outcome=body.simulate, idempotency_key=idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return payment


async def verified_webhook_body(request: Request, x_signature: str | None = Header(None)) -> bytes:
    """The signature covers the exact raw bytes, so verify before parsing anything."""
    body = await request.body()
    if not x_signature or not verify_webhook_signature(body, x_signature):
        raise AuthenticationError("Invalid webhook signature")
    return body


@router.post(
    "/webhook/",
    response_model=WebhookOut,
    responses=error_responses(
        401, 404, 422, _401="Missing or invalid X-Signature", _404="Unknown provider_ref"
    ),
    # The body is read raw (for the signature check), so describe its schema explicitly.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": WebhookIn.model_json_schema()}},
        }
    },
)
def payment_webhook(body: bytes = Depends(verified_webhook_body), db: Session = Depends(get_db)):
    try:
        event = WebhookIn.model_validate_json(body)
    except ValidationError as exc:
        # Same shape as FastAPI's own body validation errors: loc starts with "body", no docs URL.
        errors = [{**e, "loc": ("body", *e["loc"])} for e in exc.errors(include_url=False)]
        raise RequestValidationError(errors)
    result, payment = payment_service.process_webhook(db, event)
    return WebhookOut(
        event_id=event.event_id,
        result=result,
        payment_status=payment.status if payment else None,
        booking_status=payment.booking.status if payment else None,
    )
