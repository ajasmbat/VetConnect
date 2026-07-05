# VetConnect

A full-stack demo app that helps U.S. veterans find nearby VA facilities and the
services they offer. Ask in plain English ("mental health near Los Angeles") or
use the search API directly.

**Scope note:** VetConnect uses **only the public VA Facilities API**. It does
not access, store, or transmit any Protected Health Information (PHI). All
secrets (VA API key, optional OpenAI key) are loaded from environment variables.

## Architecture

```
┌────────────────────┐   HTTP    ┌───────────────────────┐   HTTPS   ┌───────────────┐
│  React + Vite + TS │ ────────► │  FastAPI (Python)     │ ────────► │  VA Facilities│
│  localhost:5173    │           │  localhost:8000       │  apikey   │  API v1       │
└────────────────────┘           │  ├─ /api/facilities   │           └───────────────┘
                                 │  ├─ /api/assistant    │
                                 │  └─ SQLite cache+log  │
                                 │  Optional: OpenAI     │
                                 └───────────────────────┘
```

- **Backend:** FastAPI + httpx (async), Pydantic v2, SQLite (stdlib) for a small
  15-min result cache and a `searches` log.
- **Frontend:** React 19 + Vite + TypeScript, plain `fetch`, minimal CSS.
- **AI assistant:** Swappable. Uses OpenAI when `OPENAI_API_KEY` is set;
  otherwise falls back to keyword parsing so the app works with zero AI setup.

Layout:

```
VetConnect/
├── backend/
│   ├── app/            # config, va_client, models, db, assistant, main
│   ├── tests/          # pytest, VA API mocked
│   └── requirements.txt
├── frontend/
│   └── src/            # App, FacilityCard, api, types, styles
├── .env.example
├── .gitignore
└── README.md
```

## Get a free VA API key

1. Go to <https://developer.va.gov/apply>.
2. Request access to the **VA Facilities API** (public data, no OAuth needed).
3. VA emails you a sandbox API key. Copy it — that's `VA_API_KEY`.

The sandbox key works against `https://sandbox-api.va.gov` which is what this
app targets by default.

## Run it

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example .env
# then edit .env and paste your VA_API_KEY

uvicorn app.main:app --reload --port 8000
```

Sanity check:

```bash
curl "http://localhost:8000/api/health"
curl "http://localhost:8000/api/facilities/search?lat=34.05&long=-118.24&radius=50"
```

Swagger docs: <http://localhost:8000/docs>

### 2. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>, type **"mental health near Los Angeles"** or click
one of the example chips.

### 3. Tests

```bash
cd backend
.venv/bin/pytest -v
```

VA API calls are mocked — tests do not touch the network.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness probe |
| `GET` | `/api/facilities/search?lat=&long=&radius=&type=&service=` | Search VA facilities |
| `GET` | `/api/facilities/{id}` | Facility detail |
| `POST` | `/api/assistant` | `{question, lat?, long?}` → answer + facilities |

All responses use Pydantic models — see `/docs` (Swagger) for full schemas.

## Optional: enable the LLM assistant

Add `OPENAI_API_KEY=sk-...` to `backend/.env` and restart. The assistant will
parse the user question with GPT and write a friendlier natural-language answer.
Without a key, the app uses keyword matching + a templated answer, and
everything still works end-to-end.

## Security notes

- Secrets live in `backend/.env` (git-ignored). Only `.env.example` is committed.
- Input validation via Pydantic on every endpoint.
- CORS is limited to the Vite dev origin (`http://localhost:5173`) — adjust
  `CORS_ORIGIN` for deploys.
- No PHI is fetched, cached, or logged. The `searches` table only stores the
  raw user question text and the parsed intent, to help iterate on the assistant.
