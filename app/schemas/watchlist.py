from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9 .&'_-]+$")
    exchange: Literal["NSE", "BSE"]

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        # Keep a single canonical representation for de-duplication.
        normalized = " ".join(value.strip().split())
        return normalized.upper()


class WatchlistItemResponse(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    resolved_symbol: str | None = None
    resolved_company_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
