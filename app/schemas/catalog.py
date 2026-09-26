from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_not_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class CentreIn(BaseModel):
    name: str = Field(max_length=200)
    city: str = Field(max_length=100)
    address: str = Field(max_length=500)

    _strip = field_validator("name", "city", "address")(_strip_not_blank)


class CentreUpdate(BaseModel):
    """PATCH body: every field optional, but at least one must be sent and none may be null or blank."""

    name: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)

    @field_validator("name", "city", "address")
    @classmethod
    def not_null_or_blank(cls, v: str | None) -> str:
        if v is None:  # only reached when null is sent explicitly; omitted fields are skipped
            raise ValueError("must not be null")
        return _strip_not_blank(v)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "CentreUpdate":
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


class CentreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str
    address: str


class DiagnosticTestIn(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("name")(_strip_not_blank)


class DiagnosticTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None


class OfferingIn(BaseModel):
    """Set the price (and availability) of a test at a centre."""

    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_active: bool = True


class OfferingOut(BaseModel):
    test_id: int
    test_name: str
    description: str | None
    price: Decimal
    is_active: bool


class CentreDetailOut(CentreOut):
    tests: list[OfferingOut]
