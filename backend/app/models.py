"""Pydantic data models — the shapes we send to and receive from the frontend.

Everything the API accepts or returns is defined here, so this file is the
single source of truth for our public schema. If you change a field, FastAPI
will automatically update the OpenAPI docs at `/docs`.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Address(BaseModel):
    """A postal address for a VA facility.

    Every field is optional because the VA API sometimes omits pieces
    (e.g. a mobile clinic may have no street number).
    """

    address_1: Optional[str] = None
    address_2: Optional[str] = None
    address_3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


class Facility(BaseModel):
    """A single VA facility, in the trimmed-down shape our API returns.

    We only expose fields the frontend actually uses. The full VA response is
    much bigger; see `va_client.facility_from_api` for the mapping.
    """

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
    """Response shape for `GET /api/facilities/search`."""

    count: int
    facilities: list[Facility]


class AssistantRequest(BaseModel):
    """Request body for `POST /api/assistant`.

    The user types a natural-language question. Optionally the browser can
    supply its own coordinates (e.g. from the geolocation API) — if present
    we skip geocoding and go straight to the VA search.
    """

    question: str = Field(..., min_length=1, max_length=500)
    lat: Optional[float] = None
    long: Optional[float] = None


class AssistantResponse(BaseModel):
    """Response body for `POST /api/assistant`.

    Fields:
        answer:          Short, friendly, plain-English reply.
        parsed_service:  What service (if any) we inferred from the question.
        parsed_location: What location (if any) we inferred from the question.
        facilities:      Matching facilities, ordered by relevance/distance.
    """

    answer: str
    parsed_service: Optional[str] = None
    parsed_location: Optional[str] = None
    facilities: list[Facility] = []


class ErrorResponse(BaseModel):
    """Generic error envelope used by non-2xx responses."""

    detail: str
