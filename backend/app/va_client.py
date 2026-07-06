"""Client for the U.S. Department of Veterans Affairs Facilities API (v1).

What this file does
-------------------
Talks to the public VA Facilities API and translates its JSON into our own
`Facility` model. Everything else in the backend uses only our clean model —
this file is the one place that knows about VA's field names and quirks.

API docs: https://developer.va.gov/explore/api/va-facilities/docs

Endpoints we call:
  * GET  {base}/facilities?lat=…&long=…&radius=…&type=…
  * GET  {base}/facilities/{id}

Authentication is a single `apikey` header. The base URL is configurable so we
can point at sandbox for development and production for real traffic. Only
public facility data is fetched — never PHI.
"""

from typing import Any, Optional

import httpx

from .config import get_settings
from .models import Address, Facility


class VAAPIError(Exception):
    """Raised when the VA API returns a non-2xx response.

    Attributes:
        status:  The HTTP status code the VA API returned (or 500 for local
                 config errors).
        message: A short, user-safe error string.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"VA API {status}: {message}")
        self.status = status
        self.message = message


def _headers() -> dict[str, str]:
    """Build the auth headers every VA request needs.

    Raises:
        VAAPIError: if `VA_API_KEY` isn't set — we treat this as a server
            misconfiguration (HTTP 500).

    Returns:
        dict[str, str]: headers dict with `apikey` and `Accept`.
    """
    key = get_settings().va_api_key
    if not key:
        raise VAAPIError(500, "VA_API_KEY is not configured on the server.")
    return {"apikey": key, "Accept": "application/json"}


def _extract_services(attrs: dict[str, Any]) -> list[str]:
    """Pull a flat list of service names out of the VA's `attributes` blob.

    The v1 API buckets services under `health`, `benefits`, and `other`, each
    a list of `{name: ...}` objects. Older/newer variants sometimes send a
    plain list of strings. We handle both shapes defensively so field-name
    churn doesn't crash us.

    Args:
        attrs: The `attributes` object from a single facility JSON item.

    Returns:
        A flat list of service-name strings (may be empty).
    """
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
    """Build an `Address` from the physical-address sub-object.

    Args:
        attrs: The `attributes` object for one facility.

    Returns:
        Address: our clean model, with `None` for any missing fields.
    """
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
    """Pick the best phone number available for the facility.

    Prefers the main number; falls back to the patient advocate line.

    Args:
        attrs: The `attributes` object for one facility.

    Returns:
        A phone string, or None if the VA record has neither field.
    """
    phone = attrs.get("phone") or {}
    return phone.get("main") or phone.get("patient_advocate") or None


def facility_from_api(item: dict[str, Any]) -> Facility:
    """Convert one raw VA facility JSON item into our `Facility` model.

    Args:
        item: A single element from the VA `data` array (with `id` +
            `attributes`).

    Returns:
        Facility: the trimmed, typed model our API returns to clients.
    """
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
    per_page: int = 40,
) -> list[Facility]:
    """Search VA facilities near a coordinate.

    Note on service filtering: we deliberately do NOT send a `services[]`
    filter to VA. Their accepted enum has changed between API versions
    (e.g. old `MentalHealthCare` → new `mentalHealth`) and a stale value
    returns HTTP 400. Instead, we fetch a larger page and filter client-side
    via `assistant.filter_by_service`.

    Args:
        lat:            Latitude (WGS84).
        long:           Longitude (WGS84).
        radius:         Search radius in miles. None uses the VA default.
        facility_type:  One of `health | benefits | cemetery | vet_center`,
                        or None to include all.
        per_page:       Page size to request from VA. Default 40.

    Raises:
        VAAPIError: on any non-200 response from VA.

    Returns:
        A list of `Facility` objects (may be empty).
    """
    base = get_settings().va_api_base_url.rstrip("/")
    params: dict[str, Any] = {"lat": lat, "long": long, "per_page": per_page}
    if radius is not None:
        params["radius"] = radius
    if facility_type:
        params["type"] = facility_type

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{base}/facilities", params=params, headers=_headers())

    if r.status_code != 200:
        raise VAAPIError(r.status_code, _safe_error(r))
    return [facility_from_api(item) for item in (r.json().get("data") or [])]


async def get_facility(facility_id: str) -> Facility:
    """Fetch a single facility by its VA id (e.g. `vha_691`).

    Args:
        facility_id: The `id` field from a VA search result.

    Raises:
        VAAPIError(404): if the id doesn't exist.
        VAAPIError:      for any other non-200 response.

    Returns:
        Facility: the requested facility.
    """
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
    """Pull a human-readable message out of a VA error response.

    The VA API is inconsistent — sometimes a `errors: [{detail: ...}]` array,
    sometimes a plain `message`, sometimes HTML. This helper covers all three
    without ever raising.

    Args:
        r: The httpx response object (assumed to be an error).

    Returns:
        A short error string, always non-empty.
    """
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
