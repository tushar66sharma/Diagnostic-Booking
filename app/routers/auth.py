from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.rate_limit import limiter
from app.schemas.auth import LoginIn, SignupIn, TokenOut, UserOut
from app.schemas.common import error_responses
from app.security import create_access_token
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup/",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409, _409="An account with this email already exists"),
)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    return auth_service.signup(db, body)


@router.post(
    "/login/", response_model=TokenOut, responses=error_responses(401, 429, _401="Invalid email or password")
)
@limiter.limit(settings.login_rate_limit)
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, body)
    return TokenOut(access_token=create_access_token(user.id), expires_in=settings.jwt_expire_minutes * 60)


@router.get("/me/", response_model=UserOut, responses=error_responses(401))
def me(user: User = Depends(get_current_user)):
    return user
