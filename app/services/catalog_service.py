import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError
from app.models import Centre, CentreTest, DiagnosticTest
from app.schemas.catalog import CentreIn, CentreUpdate, DiagnosticTestIn, OfferingIn, OfferingOut
from app.schemas.common import PageParams

logger = logging.getLogger(__name__)


def create_centre(db: Session, data: CentreIn) -> Centre:
    centre = Centre(**data.model_dump())
    db.add(centre)
    db.commit()
    logger.info("centre.created", extra={"centre_id": centre.id})
    return centre


def update_centre(db: Session, centre_id: int, data: CentreUpdate) -> Centre:
    centre = db.get(Centre, centre_id)
    if centre is None:
        raise NotFoundError("Centre not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(centre, field, value)
    db.commit()
    logger.info("centre.updated", extra={"centre_id": centre.id, "fields": sorted(changes)})
    return centre


def list_centres(
    db: Session, page: PageParams, city: str | None = None, test_id: int | None = None
) -> tuple[list[Centre], int]:
    query = select(Centre)
    if city:
        query = query.where(func.lower(Centre.city) == city.strip().lower())
    if test_id is not None:
        query = query.where(
            Centre.id.in_(select(CentreTest.centre_id).where(CentreTest.test_id == test_id, CentreTest.is_active))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Centre.id).offset(page.offset).limit(page.page_size)).all()
    return list(items), total


def get_centre(db: Session, centre_id: int) -> Centre:
    centre = db.scalar(
        select(Centre)
        .where(Centre.id == centre_id)
        .options(selectinload(Centre.offerings).selectinload(CentreTest.test))
    )
    if centre is None:
        raise NotFoundError("Centre not found")
    return centre


def offering_out(offering: CentreTest) -> OfferingOut:
    return OfferingOut(
        test_id=offering.test_id,
        test_name=offering.test.name,
        description=offering.test.description,
        price=offering.price,
        is_active=offering.is_active,
    )


def active_offerings(centre: Centre) -> list[OfferingOut]:
    return [offering_out(o) for o in sorted(centre.offerings, key=lambda o: o.test.name) if o.is_active]


def create_test(db: Session, data: DiagnosticTestIn) -> DiagnosticTest:
    test = DiagnosticTest(**data.model_dump())
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("A test with this name already exists")
    return test


def list_tests(db: Session, page: PageParams) -> tuple[list[DiagnosticTest], int]:
    total = db.scalar(select(func.count()).select_from(DiagnosticTest))
    items = db.scalars(select(DiagnosticTest).order_by(DiagnosticTest.name).offset(page.offset).limit(page.page_size))
    return list(items), total


def set_offering(db: Session, centre_id: int, test_id: int, data: OfferingIn) -> CentreTest:
    """Create or update the price of a test at a centre (idempotent PUT semantics)."""
    if db.get(Centre, centre_id) is None:
        raise NotFoundError("Centre not found")
    test = db.get(DiagnosticTest, test_id)
    if test is None:
        raise NotFoundError("Test not found")

    offering = db.scalar(select(CentreTest).where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id))
    if offering is None:
        offering = CentreTest(centre_id=centre_id, test_id=test_id)
        db.add(offering)
    offering.price = data.price
    offering.is_active = data.is_active
    try:
        db.commit()
    except IntegrityError:  # two admins creating the same offering at once
        db.rollback()
        raise ConflictError("Offering was modified concurrently, please retry")
    logger.info(
        "offering.set",
        extra={"centre_id": centre_id, "test_id": test_id, "price": str(data.price), "is_active": data.is_active},
    )
    return offering
