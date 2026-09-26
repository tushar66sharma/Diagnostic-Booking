import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings
from app.errors import AuthenticationError


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """Return the user id in a valid token, or raise AuthenticationError."""
    try:
        claims = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["exp", "sub"]}
        )
        return int(claims["sub"])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except (jwt.InvalidTokenError, ValueError):
        raise AuthenticationError("Invalid authentication token")


def sign_webhook_payload(body: bytes) -> str:
    """HMAC-SHA256 of the raw request body, hex encoded. The provider sends it in X-Signature."""
    return hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_webhook_payload(body), signature)
