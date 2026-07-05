"""VetConnect FastAPI app.

Scope note: this service consumes only the public VA Facilities API. It does
not fetch, store, or transmit any Protected Health Information (PHI). Secrets
(VA_API_KEY, OPENAI_API_KEY) are read from environment variables via
`app.config.Settings` and never committed to the repo.
"""

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import assistant, db
from .config import get_settings
from .geocode import geocode_city
from .models import (
    AssistantRequest,
    AssistantResponse,
    ErrorResponse,
    Facility,
    SearchResponse,
)
from .va_client import VAAPIError, get_facility, search_facilities


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="VetConnect API",
    description=(
        "Helps U.S. veterans find nearby VA facilities and services. "
        "Uses only the public VA Facilities API — no PHI is processed."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().cors_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _cache_key(**parts) -> str:
    return json.dumps(parts, sort_keys=True, default=str)


@app.get("/api/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/facilities/search",
    response_model=SearchResponse,
    responses={502: {"model": ErrorResponse}},
    summary="Search VA facilities by location, type, and service",
)
async def search(
    lat: float = Query(..., ge=-90, le=90),
    long: float = Query(..., ge=-180, le=180),
    radius: Optional[float] = Query(50, gt=0, le=500, description="Miles"),
    type: Optional[str] = Query(
        None, description="health | benefits | cemetery | vet_center"
    ),
    service: Optional[str] = Query(None, description="e.g. MentalHealthCare"),
) -> SearchResponse:
    key = _cache_key(kind="search", lat=lat, long=long, radius=radius, type=type, service=service)
    cached = db.get_cached(key)
    if cached:
        return SearchResponse(**cached)

    try:
        results = await search_facilities(lat, long, radius, type, service)
    except VAAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)

    resp = SearchResponse(count=len(results), facilities=results)
    db.set_cached(key, resp.model_dump())
    return resp


@app.get(
    "/api/facilities/{facility_id}",
    response_model=Facility,
    responses={404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    summary="Get one facility by VA facility id",
)
async def detail(facility_id: str) -> Facility:
    key = _cache_key(kind="detail", id=facility_id)
    cached = db.get_cached(key)
    if cached:
        return Facility(**cached)
    try:
        f = await get_facility(facility_id)
    except VAAPIError as e:
        raise HTTPException(status_code=e.status if e.status in (404,) else 502, detail=e.message)
    db.set_cached(key, f.model_dump())
    return f


@app.post(
    "/api/assistant",
    response_model=AssistantResponse,
    responses={502: {"model": ErrorResponse}},
    summary="Answer a plain-English question with matching facilities",
)
async def assistant_endpoint(req: AssistantRequest) -> AssistantResponse:
    service, location_hint = await assistant.llm_parse(req.question)

    # Resolve coordinates: explicit lat/long > parsed city > geocode from raw question.
    lat, long_ = req.lat, req.long
    if lat is None or long_ is None:
        coords = None
        if location_hint:
            coords = geocode_city(location_hint)
        if not coords:
            coords = geocode_city(req.question)
        if coords:
            lat, long_ = coords

    db.log_question(req.question, service, location_hint)

    if lat is None or long_ is None:
        return AssistantResponse(
            answer=(
                "I couldn't figure out which city you meant. Try adding one — "
                "e.g. 'mental health near Los Angeles'."
            ),
            parsed_service=service,
            parsed_location=location_hint,
            facilities=[],
        )

    try:
        results = await search_facilities(lat, long_, radius=50, service=service)
    except VAAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)

    answer = await assistant.write_answer(req.question, service, location_hint, results)
    return AssistantResponse(
        answer=answer,
        parsed_service=service,
        parsed_location=location_hint,
        facilities=results,
    )
