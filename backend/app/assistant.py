"""AI assistant: turn a plain-English question into a facility search + answer.

Two backends sit behind the same interface:

    * LLM (OpenAI)   — automatic when `OPENAI_API_KEY` is set.
    * Keyword parser — used otherwise. Deterministic, no network, still useful.

So the whole app works end-to-end without any AI setup — the answers are just
less conversational. Adding another provider (Anthropic, local model) is a
matter of adding another branch in `llm_parse` / `write_answer`.
"""

import json
import re
from typing import Optional

import httpx

from .config import get_settings
from .models import Facility

# The service "catalog." Keys are the canonical service names we return; values
# are the everyday phrasings users are likely to type. Order matters: the first
# alias that appears in the question wins, so more-specific phrases should come
# before generic ones within each list.
SERVICE_ALIASES: dict[str, list[str]] = {
    # ---- Existing (original 12) ------------------------------------------
    # Note: no bare "therapy" or "counseling" — both are generic VA terms
    # that appear in Physical therapy, Recreation therapy, career counseling,
    # and grief counseling labels, none of which are mental health services.
    # Users can still be routed here via "mental health", "psychiatry", etc.
    # Include practitioner forms too: "psychiatrist"/"psychologist" don't
    # contain "psychiatry"/"psychology" as substrings.
    "MentalHealthCare": [
        "mental health", "psychiatry", "psychiatrist",
        "psychology", "psychologist",
        "ptsd", "depression", "anxiety",
    ],
    "PrimaryCare": ["primary care", "family doctor", "general practitioner", "checkup"],
    "DentalServices": ["dental", "dentist", "teeth", "oral surgery"],
    # Note: no bare "er" alias — it appears in almost every word
    # ("Veteran", "Caregiver", "counseling"...) and would false-match everything.
    "EmergencyCare": ["emergency care", "emergency", "urgent care", "urgent"],
    "Cardiology": ["cardiology", "heart", "cardiac"],
    "Optometry": ["optometry", "eye", "vision", "glasses"],
    "Audiology": ["audiology", "hearing", "hearing aid", "speech"],
    "Pharmacy": ["pharmacy", "prescription", "medication"],
    # WomensHealth: VA renamed this label to "Women Veteran care" — added
    # "women veteran" aliases so we still match the current v1 responses.
    # Include the bare "women health" (no apostrophe, no "s") since users
    # often drop punctuation and inflection when typing.
    "WomensHealth": [
        "womens health", "women's health", "women health",
        "women veteran", "women veterans",
        "gynecology", "obgyn",
    ],
    "Nutrition": ["nutrition", "dietitian", "diet", "food"],
    # Note: no bare "pt" alias — it appears as a substring of "adaptive",
    # "optometry", etc. No "rehab" either — it substring-matches
    # "Vocational rehabilitation" (a jobs benefit, not PT) and
    # "Blind and low vision rehabilitation" (eye service, not PT).
    # "physical medicine" catches VA's "Physical medicine and rehabilitation".
    "PhysicalTherapy": [
        "physical therapy", "occupational therapy", "physical medicine",
    ],
    # Homelessness: matches both the health label "Homeless Veteran care"
    # and the benefits label "HomelessAssistance" via the "homeless" alias.
    "Homelessness": ["homeless", "housing"],

    # ---- New (added to cover the rest of the VA v1 health catalog) -------
    "Cancer": ["cancer", "chemo", "chemotherapy", "oncology", "tumor"],
    "Dermatology": ["dermatology", "dermatologist", "skin", "rash", "acne"],
    "Orthopedics": [
        "orthopedic", "orthopedics", "ortho", "bone", "joint",
        "knee pain", "back pain", "shoulder",
    ],
    "Podiatry": ["podiatry", "podiatrist", "foot", "feet", "ankle"],
    "Urology": ["urology", "urologist", "prostate", "bladder"],
    # Note: no bare "gi" alias — matches "caregiver", "eBenefits...gistration",
    # and any word with "gi" in the middle. Use "gi doctor" if you must.
    "Gastroenterology": [
        "gastroenterology", "gi doctor", "stomach", "colonoscopy", "digestive",
    ],
    "Neurology": ["neurology", "neurologist", "migraine", "seizure", "stroke"],
    "Endocrinology": [
        "endocrinology", "diabetes", "thyroid", "hormone",
    ],
    "Rheumatology": ["rheumatology", "arthritis", "lupus"],
    "PainManagement": ["pain management", "chronic pain"],
    "SleepMedicine": ["sleep medicine", "sleep apnea", "cpap", "insomnia"],
    "Chiropractic": ["chiropractic", "chiropractor"],
    "Vaccines": [
        "vaccine", "vaccines", "shots", "immunization", "flu shot", "covid",
    ],
    "Radiology": ["radiology", "x-ray", "xray", "mri", "ct scan", "imaging"],
    "SubstanceUse": [
        "substance use", "substance abuse", "addiction", "alcohol",
        "drug", "detox",
    ],
    "SuicidePrevention": ["suicide", "crisis line", "hotline"],
    "CaregiverSupport": ["caregiver", "family caregiver"],
    "Geriatrics": ["geriatrics", "elderly", "senior care"],
    "SmokingCessation": [
        "smoking", "tobacco", "quit smoking", "nicotine",
    ],
    "Telehealth": ["telehealth", "virtual visit", "video visit", "remote visit"],
}


def _match_service(text: str) -> Optional[str]:
    """Find the canonical service whose aliases appear in `text`.

    Uses longest-alias-wins: if the input contains multiple matching aliases
    (e.g. "physical therapy" hits both PhysicalTherapy's "physical therapy"
    AND MentalHealthCare's generic "therapy"), we return the service whose
    matched alias was the longest, since long aliases are more specific.

    Args:
        text: Any user-typed string.

    Returns:
        The canonical service name (e.g. "MentalHealthCare"), or None if no
        alias appears in the text.
    """
    t = text.lower()
    best_service: Optional[str] = None
    best_len = 0
    for service, aliases in SERVICE_ALIASES.items():
        for alias in aliases:
            if alias in t and len(alias) > best_len:
                best_service = service
                best_len = len(alias)
    return best_service


def _normalize(s: str) -> str:
    """Split CamelCase into words, collapse whitespace, lowercase.

    Examples:
        "MentalHealthCare"    -> "mental health care"
        "Women Veteran care"  -> "women veteran care"   (collapses double space)
        "mental Health Care"  -> "mental health care"

    We need this because the VA API has changed casing conventions across
    versions ("MentalHealthCare" vs "Mental health care") and we want to
    match either. Collapsing whitespace matters because inserting a space
    before every capital can create double spaces when the string already
    had one there (e.g. "Women Veteran" -> "women  veteran").

    Args:
        s: The string to normalize.

    Returns:
        The lowercase, single-space-separated form.
    """
    # Two-step CamelCase split that keeps runs of capitals together:
    #   1. Insert space between a lowercase/digit and a following uppercase.
    #      "MentalHealthCare" -> "Mental Health Care"
    #   2. Insert space between a run of uppercase and an uppercase-lowercase
    #      pair. "PTSDCare" -> "PTSD Care". Leaves "PTSD care" alone.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return re.sub(r"\s+", " ", spaced).strip().lower()


def filter_by_service(
    facilities: list[Facility], service: Optional[str]
) -> list[Facility]:
    """Keep only facilities that provide the given service.

    A facility is kept if any of its own service labels contains any of the
    aliases we know for `service`. Matching is case- and separator-insensitive
    (see `_normalize`).

    Args:
        facilities: The list of facilities to filter.
        service:    Canonical service name, or None. If None, no filtering
                    happens and `facilities` is returned unchanged.

    Returns:
        The filtered list (may be empty).
    """
    if not service:
        return facilities
    aliases = [service, *SERVICE_ALIASES.get(service, [])]
    needles = {_normalize(a) for a in aliases if a}
    kept: list[Facility] = []
    for f in facilities:
        haystack = " | ".join(_normalize(s) for s in f.services)
        if any(n in haystack for n in needles):
            kept.append(f)
    return kept


def _extract_location_hint(text: str) -> Optional[str]:
    """Pull the location out of a user question.

    Two strategies, tried in order:
        1. A preposition + place: "near X", "in X", "around X", "by X",
           "closest to X", "nearest to X" — anything from the preposition to
           the end of the string.
        2. A Title-Case run at the very end: for queries with no preposition
           at all (e.g. "prescription refill Denver", "flu shot Dallas"),
           grab the trailing capitalized word(s) as the likely place name.
           Won't fire mid-sentence — only if the Title-Case run is at the tail.

    Args:
        text: The full user question.

    Returns:
        The extracted place string, or None if neither strategy matches.
    """
    m = re.search(r"\b(?:near|in|around|by|closest to|nearest to)\s+([A-Za-z .,'-]+)$", text, re.I)
    if m:
        return m.group(1).strip(" .,")

    # Fallback: trailing capitalized word(s) — "…refill Denver",
    # "…care San Antonio", "…in Salt Lake City", "…management LA".
    # `[A-Z][A-Za-z]*` accepts both Title Case ("Denver") and all-caps
    # abbreviations ("LA", "NYC", "DC").
    tail = re.search(r"(?:^|\s)([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\s*$", text)
    return tail.group(1).strip() if tail else None


def keyword_parse(question: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort parse using only regex/keywords (no network).

    Used when OpenAI isn't configured, or as a fallback when the LLM call
    fails.

    Args:
        question: The user's question.

    Returns:
        (service, location) — either or both may be None.
    """
    return _match_service(question), _extract_location_hint(question)


async def llm_parse(question: str) -> tuple[Optional[str], Optional[str]]:
    """Use OpenAI to extract {service, location} from the question.

    Sends a tiny system prompt asking for strict JSON. If anything about the
    call fails (no key, HTTP error, malformed JSON, timeout), we fall back to
    `keyword_parse` so the endpoint still responds.

    Args:
        question: The user's question.

    Returns:
        (service, location). `service` is guaranteed to be either a valid
        `SERVICE_ALIASES` key or None. `location` is a free-form string or
        None.
    """
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
                settings.openai_api_base_url,
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
    """Compose the short, friendly reply shown to the user.

    Two paths, same signature:
        * If OpenAI is configured AND we have facilities to talk about, ask
          the model for a 2–4 sentence answer grounded in the top 5 results.
        * Otherwise (or if the LLM call fails), build a deterministic string
          via `_template_answer`.

    Args:
        question:   The original user question (for context in the LLM prompt).
        service:    Parsed service name, or None.
        location:   Parsed location string, or None.
        facilities: Matching facilities, in order.

    Returns:
        A single string suitable for direct display to the user.
    """
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
                settings.openai_api_base_url,
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
    """Deterministic answer builder used when we can't (or don't) call the LLM.

    Two shapes:
        * No facilities  -> apologetic "couldn't find anything" message.
        * Some results   -> "Closest match: {name} in {city}, {state}. Plus N more."

    Args:
        service:    Parsed service name, or None.
        location:   Parsed location string, or None.
        facilities: Matching facilities, in order.

    Returns:
        A single, ready-to-display sentence.
    """
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
