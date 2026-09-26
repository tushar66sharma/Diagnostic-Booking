import os
from decimal import Decimal
from pathlib import Path

# Point the app at the test database *before* anything from `app` is imported.
# Overwrite (not setdefault) so a DATABASE_URL in the shell can never make tests wipe the dev DB.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://eve:eve_password@localhost:5433/eve_test"
)

os.environ["BCRYPT_ROUNDS"] = "4"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Centre, CentreTest, DiagnosticTest, User  # noqa: E402
from app.rate_limit import limiter  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TABLES = "users, centres, diagnostic_tests, centre_tests, bookings, payments, webhook_events"


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Build the schema with the real migrations, so the tests also prove the migrations work."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = os.environ["DATABASE_URL"]
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_state():
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    limiter.reset()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(db, email="user@example.com", password="Passw0rd!", is_admin=False, full_name="Test User"):
    user = User(email=email, full_name=full_name, password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.commit()
    return user


def auth_headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_offering(db, price="500.00", centre_name="City Diagnostics", city="Pune", test_name="Complete Blood Count"):
    centre = db.scalar(select(Centre).where(Centre.name == centre_name)) or Centre(
        name=centre_name, city=city, address="1 MG Road"
    )
    test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == test_name)) or DiagnosticTest(name=test_name)
    offering = CentreTest(centre=centre, test=test, price=Decimal(price))
    db.add(offering)
    db.commit()
    return offering


@pytest.fixture
def offering(db):
    return make_offering(db)


@pytest.fixture
def user(db):
    return make_user(db)


@pytest.fixture
def other_user(db):
    return make_user(db, email="other@example.com")


@pytest.fixture
def admin(db):
    return make_user(db, email="admin@example.com", is_admin=True)
