import logging
import time
import uuid

from fastapi import Depends, FastAPI, Request
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError, app_error_handler, rate_limit_handler
from app.logging_config import configure_logging
from app.rate_limit import limiter
from app.routers import auth, bookings, catalog, payments

configure_logging(settings.log_level)
logger = logging.getLogger("app.request")

app = FastAPI(
    title="EVE Diagnostic Bookings API",
    version="1.0.0",
    description="Book diagnostic tests at partner centres and pay through a simulated payment provider.",
)
app.state.limiter = limiter
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(bookings.router)
app.include_router(payments.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
