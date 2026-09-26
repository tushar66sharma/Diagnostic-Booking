from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.schemas.catalog import (
    CentreDetailOut,
    CentreIn,
    CentreOut,
    CentreUpdate,
    DiagnosticTestIn,
    DiagnosticTestOut,
    OfferingIn,
    OfferingOut,
)
from app.schemas.common import Page, PageParams, error_responses
from app.services import catalog_service

router = APIRouter(tags=["catalog"])

ADMIN_ERRORS = (401, 403)


@router.get("/centres/", response_model=Page[CentreOut])
def list_centres(
    page: PageParams = Depends(),
    city: str | None = Query(None, max_length=100, description="Case-insensitive city match"),
    test_id: int | None = Query(None, description="Only centres currently offering this test"),
    db: Session = Depends(get_db),
):
    items, total = catalog_service.list_centres(db, page, city=city, test_id=test_id)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/centres/{centre_id}/", response_model=CentreDetailOut, responses=error_responses(404))
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    centre = catalog_service.get_centre(db, centre_id)
    return CentreDetailOut(
        **CentreOut.model_validate(centre).model_dump(), tests=catalog_service.active_offerings(centre)
    )


@router.post(
    "/centres/",
    response_model=CentreOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERRORS),
)
def create_centre(body: CentreIn, db: Session = Depends(get_db)):
    return catalog_service.create_centre(db, body)


@router.patch(
    "/centres/{centre_id}/",
    response_model=CentreOut,
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERRORS, 404),
)
def update_centre(centre_id: int, body: CentreUpdate, db: Session = Depends(get_db)):
    """Partial update: send only the fields to change."""
    return catalog_service.update_centre(db, centre_id, body)


@router.put(
    "/centres/{centre_id}/tests/{test_id}/",
    response_model=OfferingOut,
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERRORS, 404, _404="Centre or test not found"),
)
def set_offering(centre_id: int, test_id: int, body: OfferingIn, db: Session = Depends(get_db)):
    """Create or update the price of a test at a centre. Set `is_active: false` to stop offering it."""
    return catalog_service.offering_out(catalog_service.set_offering(db, centre_id, test_id, body))


@router.get("/tests/", response_model=Page[DiagnosticTestOut])
def list_tests(page: PageParams = Depends(), db: Session = Depends(get_db)):
    items, total = catalog_service.list_tests(db, page)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.post(
    "/tests/",
    response_model=DiagnosticTestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERRORS, 409, _409="A test with this name already exists"),
)
def create_test(body: DiagnosticTestIn, db: Session = Depends(get_db)):
    return catalog_service.create_test(db, body)
