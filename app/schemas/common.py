from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


@dataclass
class PageParams:
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorOut(BaseModel):
    detail: str


_ERROR_DESCRIPTIONS = {
    401: "Missing, invalid or expired credentials",
    403: "Authenticated but not allowed (admin only)",
    404: "Resource not found (or not owned by the caller)",
    409: "Request conflicts with the current state of the resource",
    422: "Request failed validation",
    429: "Rate limit exceeded",
}


def error_responses(*codes: int, **overrides: str) -> dict[int | str, dict]:
    """OpenAPI `responses` entries for the error codes an endpoint can return.
    Override a description with e.g. `_409="Booking is not payable"`."""
    return {
        code: {"model": ErrorOut, "description": overrides.get(f"_{code}", _ERROR_DESCRIPTIONS[code])}
        for code in codes
    }
