import os

import pytest
from fastapi.testclient import TestClient

# Configure env before importing the app so Settings picks it up.
os.environ["VA_API_KEY"] = "test-key"
os.environ["OPENAI_API_KEY"] = ""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VA_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    # Reset settings + point SQLite at a fresh temp file per test.
    from app import config

    config.get_settings.cache_clear()
    settings = config.get_settings()
    settings.sqlite_path = str(tmp_path / "test.db")

    # Rate limiter is a module-level singleton; clear it so per-IP counts
    # from one test don't bleed into the next.
    from app.rate_limit import limiter

    limiter.reset()

    from app.main import app

    with TestClient(app) as c:
        yield c


SAMPLE_FACILITY = {
    "id": "vha_691",
    "type": "va_facilities",
    "attributes": {
        "name": "West Los Angeles VA Medical Center",
        "facility_type": "va_health_facility",
        "classification": "VA Medical Center (VAMC)",
        "website": "https://www.va.gov/greater-los-angeles-health-care/",
        "lat": 34.0561,
        "long": -118.4527,
        "address": {
            "physical": {
                "address_1": "11301 Wilshire Boulevard",
                "city": "Los Angeles",
                "state": "CA",
                "zip": "90073",
            }
        },
        "phone": {"main": "310-478-3711"},
        "hours": {"monday": "24/7"},
        "services": {
            "health": [
                {"name": "MentalHealthCare"},
                {"name": "PrimaryCare"},
                {"name": "DentalServices"},
            ]
        },
    },
}
