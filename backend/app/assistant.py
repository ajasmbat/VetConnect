"""AI assistant for turning a plain-English question into a facility search.

Two backends live behind the same `parse_question` / `write_answer` interface:
  * LLM (OpenAI) — used automatically when OPENAI_API_KEY is set.
  * Keyword fallback — used otherwise, so the app runs end-to-end with no AI setup.

Swapping providers is a matter of adding another branch here.
"""

import json
import re
from typing import Optional

import httpx

from .config import get_settings
from .models import Facility

# Canonical service catalog. Keys are what we search on; values are colloquial
# phrasings the assistant should map to that service.
SERVICE_ALIASES: dict[str, list[str]] = {
    "MentalHealthCare": [
        "mental health", "therapy", "counseling", "psychiatry", "psychology",
        "ptsd", "depression", "anxiety",
    ],
    "PrimaryCare": ["primary care", "family doctor", "general practitioner", "checkup"],
    "DentalServices": ["dental", "dentist", "teeth"],
    "EmergencyCare": ["emergency", "er", "urgent"],
    "Cardiology": ["cardiology", "heart", "cardiac"],
    "Optometry": ["optometry", "eye", "vision", "glasses"],
    "Audiology": ["audiology", "hearing", "hearing aid"],
    "Pharmacy": ["pharmacy", "prescription", "medication"],
    "WomensHealth": ["womens health", "women's health", "gynecology", "obgyn"],
    "Nutrition": ["nutrition", "dietitian", "diet"],
    "PhysicalTherapy": ["physical therapy", "pt", "rehab"],
    "Homelessness": ["homeless", "housing"],
}


def _match_service(text: str) -> Optional[str]:
    t = text.lower()
    for service, aliases in SERVICE_ALIASES.items():
        for alias in aliases:
            if alias in t:
                return service
    return None


def _extract_location_hint(text: str) -> Optional[str]:
    """Pull a rough location string from patterns like 'near X' or 'in X'."""
    m = re.search(r"\b(?:near|in|around|by|closest to|nearest to)\s+([A-Za-z .,'-]+)$", text, re.I)
    return m.group(1).strip(" .,") if m else None


def keyword_parse(question: str) -> tuple[Optional[str], Optional[str]]:
    return _match_service(question), _extract_location_hint(question)


async def llm_parse(question: str) -> tuple[Optional[str], Optional[str]]:
    """Ask the LLM for a strict JSON {service, location}. Fall back to keyword
    matching if anything about the call fails."""
    settings = get_settings()
    if not settings.openai_api_key:
        return keyword_parse(question)

    system = (
        "You extract structured intent from short veteran health questions. "
        "Return ONLY compact JSON with keys 'service' and 'location'. "
        f"service must be one of: {list(SERVICE_ALIASES)} or null. "
        "location is a U.S. city or region string, or null."
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": question},
                    ],
                },
            )
        if r.status_code != 200:
            return keyword_parse(question)
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        service = data.get("service") if data.get("service") in SERVICE_ALIASES else None
        location = data.get("location") or None
        return service, location
    except Exception:
        return keyword_parse(question)


async def write_answer(
    question: str,
    service: Optional[str],
    location: Optional[str],
    facilities: list[Facility],
) -> str:
    """Craft a short, friendly answer. LLM if configured, template otherwise."""
    settings = get_settings()
    top = facilities[:5]

    if not settings.openai_api_key or not top:
        return _template_answer(service, location, top)

    facts = [
        {
            "name": f.name,
            "city": f.address.city,
            "state": f.address.state,
            "phone": f.phone,
            "services": f.services[:6],
        }
        for f in top
    ]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "temperature": 0.3,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are VetConnect, a friendly assistant for U.S. veterans. "
                                "Answer in 2–4 sentences. Mention 1–2 facilities by name and "
                                "city. Do not invent facts outside the provided data. Never ask "
                                "for personal or medical details."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"question": question, "facilities": facts}
                            ),
                        },
                    ],
                },
            )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return _template_answer(service, location, top)


def _template_answer(
    service: Optional[str], location: Optional[str], facilities: list[Facility]
) -> str:
    if not facilities:
        loc = f" near {location}" if location else ""
        svc = f" offering {service}" if service else ""
        return (
            f"I couldn't find VA facilities{svc}{loc}. Try widening the radius "
            "or a nearby city."
        )
    top = facilities[0]
    others = len(facilities) - 1
    where = ", ".join(x for x in [top.address.city, top.address.state] if x)
    svc = f" for {service}" if service else ""
    tail = f" Plus {others} more nearby." if others > 0 else ""
    return f"Closest match{svc}: {top.name}{' in ' + where if where else ''}.{tail}"
