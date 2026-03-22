from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreateRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=100)

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class WatchlistItemResponse(BaseModel):
    id: UUID
    symbol: str | None
    exchange: str | None
    company_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
