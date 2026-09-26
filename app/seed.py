"""Load demo data: an admin user, a few tests and centres with prices. Safe to run repeatedly.

    python -m app.seed
"""

import os
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Centre, CentreTest, DiagnosticTest, User
from app.security import hash_password

TESTS = {
    "Complete Blood Count": "Haemoglobin, WBC, RBC and platelet counts",
    "Lipid Profile": "Total cholesterol, HDL, LDL and triglycerides",
    "Thyroid Profile": "T3, T4 and TSH",
    "HbA1c": "Average blood sugar over three months",
}

CENTRES = [
    ("Apollo Diagnostics Koramangala", "Bengaluru", "80 Feet Road, Koramangala",
     {"Complete Blood Count": "350", "Lipid Profile": "650", "HbA1c": "499"}),
    ("Metropolis Andheri", "Mumbai", "Veera Desai Road, Andheri West",
     {"Complete Blood Count": "400", "Thyroid Profile": "550", "Lipid Profile": "700"}),
    ("Dr Lal PathLabs Saket", "Delhi", "Press Enclave Marg, Saket",
     {"Complete Blood Count": "300", "Thyroid Profile": "480", "HbA1c": "450"}),
]


def get_or_create(db: Session, model, lookup: dict, **defaults):
    obj = db.scalar(select(model).filter_by(**lookup))
    if obj is None:
        obj = model(**lookup, **defaults)
        db.add(obj)
        db.flush()
    return obj


# Must pass the same email validation as login (reserved TLDs such as .test are rejected).
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345")


def seed(db: Session) -> None:
    get_or_create(
        db, User, {"email": ADMIN_EMAIL.lower()},
        full_name="EVE Admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        is_admin=True,
    )
    tests = {name: get_or_create(db, DiagnosticTest, {"name": name}, description=desc) for name, desc in TESTS.items()}
    for name, city, address, prices in CENTRES:
        centre = get_or_create(db, Centre, {"name": name}, city=city, address=address)
        for test_name, price in prices.items():
            get_or_create(db, CentreTest, {"centre_id": centre.id, "test_id": tests[test_name].id}, price=Decimal(price))
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
    if "SEED_ADMIN_PASSWORD" in os.environ:  # never print a real password into hosted logs
        print(f"Seed data loaded. Admin login: {ADMIN_EMAIL} (password from SEED_ADMIN_PASSWORD)")
    else:
        print(f"Seed data loaded. Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
