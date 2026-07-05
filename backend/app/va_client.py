"""Async client for the VA Facilities API v1.

Docs: https://developer.va.gov/explore/api/va-facilities/docs

Endpoints used:
  GET {base}/facilities?lat=&long=&radius=&type=&services[]=
  GET {base}/facilities/{id}

Auth is a single header, `apikey`. The base URL is configurable so we can point
at sandbox vs production. Only public facility data is fetched (no PHI).
"""

from typing import Any, Optional

import httpx

from .config import get_settings
from .models import Address, Facility


class VAAPIError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"VA API {status}: {message}")
        self.status = status
        self.message = message


def _headers() -> dict[str, str]:
    key = get_settings().va_api_key
    if not key:
        raise VAAPIError(500, "VA_API_KEY is not configured on the server.")
    return {"apikey": key, "Accept": "application/json"}


def _extract_services(attrs: dict[str, Any]) -> list[str]:
    """The v1 response nests services under health/benefits/other lists of
    objects with `name`. Older/newer variants sometimes return a flat list.
    Handle both shapes defensively."""
    raw = attrs.get("services") or {}
    if isinstance(raw, list):
        return [s if isinstance(s, str) else s.get("name", "") for s in raw if s]
    out: list[str] = []
    for bucket in ("health", "benefits", "other"):
        for item in raw.get(bucket, []) or []:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("sl1") or ""
                if name:
                    out.append(name)
    return out


def _extract_address(attrs: dict[str, Any]) -> Address:
    addr = (attrs.get("address") or {}).get("physical") or {}
    return Address(
        address_1=addr.get("address_1"),
        address_2=addr.get("address_2"),
        address_3=addr.get("address_3"),
        city=addr.get("city"),
        state=addr.get("state"),
        zip=addr.get("zip"),
    )


def _extract_phone(attrs: dict[str, Any]) -> Optional[str]:
    phone = attrs.get("phone") or {}
    return phone.get("main") or phone.get("patient_advocate") or None


def facility_from_api(item: dict[str, Any]) -> Facility:
    attrs = item.get("attributes") or {}
    return Facility(
        id=item.get("id", ""),
        name=attrs.get("name", "Unknown"),
        type=attrs.get("facility_type"),
        classification=attrs.get("classification"),
        address=_extract_address(attrs),
        phone=_extract_phone(attrs),
        lat=attrs.get("lat"),
        long=attrs.get("long"),
        services=_extract_services(attrs),
        hours=attrs.get("hours") or {},
        website=attrs.get("website"),
        distance=attrs.get("distance"),
    )


async def search_facilities(
    lat: float,
    long: float,
    radius: Optional[float] = None,
    facility_type: Optional[str] = None,
    service: Optional[str] = None,
    per_page: int = 20,
) -> list[Facility]:
    base = get_settings().va_api_base_url.rstrip("/")
    params: dict[str, Any] = {"lat": lat, "long": long, "per_page": per_page}
    if radius is not None:
        params["radius"] = radius
    if facility_type:
        params["type"] = facility_type
    if service:
        # v1 accepts `services[]` for multi-value; we send a single value.
        params["services[]"] = service

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{base}/facilities", params=params, headers=_headers())

    if r.status_code != 200:
        raise VAAPIError(r.status_code, _safe_error(r))
    return [facility_from_api(item) for item in (r.json().get("data") or [])]


async def get_facility(facility_id: str) -> Facility:
    base = get_settings().va_api_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{base}/facilities/{facility_id}", headers=_headers()
        )
    if r.status_code == 404:
        raise VAAPIError(404, f"Facility '{facility_id}' not found.")
    if r.status_code != 200:
        raise VAAPIError(r.status_code, _safe_error(r))
    data = r.json().get("data") or {}
    return facility_from_api(data)


def _safe_error(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                return str(errors[0].get("detail") or errors[0])
            if "message" in body:
                return str(body["message"])
        return r.text[:200]
    except Exception:
        return r.text[:200] or "Unknown error"
