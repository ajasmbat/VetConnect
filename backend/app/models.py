from typing import Optional

from pydantic import BaseModel, Field


class Address(BaseModel):
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


class Facility(BaseModel):
    """Simplified facility shape returned by our API."""

    id: str
    name: str
    type: Optional[str] = Field(None, description="e.g. va_health_facility")
    classification: Optional[str] = None
    address: Address = Address()
    phone: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    services: list[str] = []
    hours: dict[str, Optional[str]] = {}
    website: Optional[str] = None
    distance: Optional[float] = None


class SearchResponse(BaseModel):
    count: int
    facilities: list[Facility]


class AssistantRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    lat: Optional[float] = None
    long: Optional[float] = None


class AssistantResponse(BaseModel):
    answer: str
    parsed_service: Optional[str] = None
    parsed_location: Optional[str] = None
    facilities: list[Facility] = []


class ErrorResponse(BaseModel):
    detail: str
