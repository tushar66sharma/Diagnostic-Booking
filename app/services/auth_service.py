import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AuthenticationError, ConflictError
from app.models import User
from app.schemas.auth import LoginIn, SignupIn
from app.security import hash_password, verify_password

logger = logging.getLogger(__name__)

# Compared against when the email is unknown, so login takes the same time either way
# and response timing does not reveal which emails are registered.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def signup(db: Session, data: SignupIn) -> User:
    user = User(email=data.email, full_name=data.full_name, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # unique(email); also covers two signups racing
        db.rollback()
        raise ConflictError("An account with this email already exists")
    logger.info("user.signed_up", extra={"user_id": user.id})
    return user


def authenticate(db: Session, data: LoginIn) -> User:
    user = db.scalar(select(User).where(User.email == data.email))
    if user is None:
        verify_password(data.password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password")
    if not verify_password(data.password, user.password_hash):
        raise AuthenticationError("Invalid email or password")
    return user
