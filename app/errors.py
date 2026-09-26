from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


class AppError(Exception):
    """Domain error raised by services; translated to an HTTP response in one place."""

    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class AuthenticationError(AppError):
    status_code = 401


class PermissionDeniedError(AppError):
    status_code = 403


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    # Same {"detail": ...} shape as every other error (slowapi's default uses {"error": ...}).
    return JSONResponse({"detail": f"Rate limit exceeded: {exc.detail}"}, status_code=429)
