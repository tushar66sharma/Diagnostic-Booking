from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import BookingStatus, User
from app.schemas.bookings import BookingDetailOut, BookingIn, BookingOut
from app.schemas.common import Page, PageParams, error_responses
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"], responses=error_responses(401))


@router.post(
    "/",
    response_model=BookingDetailOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        404, 409,
        _404="The centre does not offer this test (or it is inactive)",
        _409="You already have an active booking for this slot",
    ),
)
def create_booking(body: BookingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return booking_service.create_booking(db, user, body)


@router.get("/", response_model=Page[BookingOut])
def list_bookings(
    page: PageParams = Depends(),
    status: BookingStatus | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = booking_service.list_user_bookings(db, user, page, status)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/{booking_id}/", response_model=BookingDetailOut, responses=error_responses(404))
def get_booking(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return booking_service.get_user_booking(db, user, booking_id)


@router.post(
    "/{booking_id}/cancel/",
    response_model=BookingDetailOut,
    responses=error_responses(404, 409, _409="Appointment time has already passed"),
)
def cancel_booking(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return booking_service.cancel_booking(db, user, booking_id)
