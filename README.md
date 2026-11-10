# FinGraph AI — Intelligence, connected.

A functional educational financial suitability platform with a premium dark interface, Python APIs, reproducible scoring, actual graph evidence, document retrieval, LangGraph orchestration, authenticated human review, and report exports.

## Run locally

Requirements: Node.js 22+, Python 3.12+, Git.

```powershell
npm ci
python -m pip install -r requirements.txt
python -m backend.migrations.001_initial
python -m backend.scripts.seed
python -m uvicorn backend.app.main:app --reload --port 8000
```

In a second terminal:

```powershell
npm run dev
```

Frontend: http://localhost:3000. Health: http://localhost:8000/api/health. OpenAPI: http://localhost:8000/api/docs.

**Demo login:** click **Enter interactive demo**. No password or paid API key is needed. This deliberately public identity has administrator/reviewer access to synthetic information only. New email/password registrations are VIEWER accounts. Disable DEMO_MODE and provision authorized accounts before any private production use. Do not enter real financial information in the demo.

## Architecture and folder structure

- `app/`: Next.js App Router shell, responsive CSS design system and API rewrite.
- `frontend/components/`: React/TypeScript workspace, Recharts analytics, React Flow graph, seven-step onboarding, product management and comparison.
- `backend/app/main.py`: FastAPI REST APIs, JWT httpOnly sessions, scrypt passwords, roles, validation, uploads, reviews, analytics, audit and reports.
- `backend/app/store.py`: SQLAlchemy transactional repository; managed PostgreSQL or local SQLite.
- `backend/app/engine.py`: actual NetworkX relationships and shared-node paths, local cosine token-vector retrieval, hard eligibility gates, weighted scoring, ten-node LangGraph execution.
- `backend/app/seed.py`: 25 synthetic investors, 30 products, 10 sample disclosures, and hundreds of consistent graph relationships. Assessments are created by users rather than invented as prior activity.
- `backend/tests/`: permissions, authentication, CRUD, graph integrity, exclusion rules, document ingestion/retrieval, review and CSV/PDF workflow tests.
- `infrastructure/`, `render.yaml`, `.github/workflows/`: Docker/PostgreSQL, optional Render API and CI.

## Features

All 14 navigation destinations connect to API data. Investor create/edit/delete, draft saving, seven-step onboarding, product CRUD, four-product comparison, reproducible suitability scoring, hard exclusions, explainability, real graph paths, document chunk citations, ten-node deterministic LangGraph pipeline, execution logs, human review comments with identity, PDF/CSV exports, risk matrix, analytics filters, audit, login/registration/logout and server-side role enforcement.

Uploads support PDF, DOCX, TXT and CSV, maximum 5 MB, with DOCX expansion checks. Extracted chunks retain document and chunk IDs. PDF page-level metadata is currently unavailable and never invented. Demo outputs use deterministic evidence summaries, not a generative LLM.

## Environment variables

See `.env.example`. Next.js loads `.env.local`; export Python environment variables in your shell or host. Set `JWT_SECRET_KEY` to a random value of at least 32 characters for consistent sessions. Use `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require` for managed PostgreSQL. Local fallback: `data/fingraph.db`. `CORS_ORIGINS` is a comma-separated allowlist.

OpenAI, Neo4j and Chroma variables document future integration points and do not activate integrations in this release. Active providers are disclosed in Settings and `/api/health`.

## Deployment

```powershell
vercel link --yes --project kg-grounded-financial-recommendation
python scripts/configure-vercel.py
vercel --prod --yes
```

Vercel serves Next.js and the Python function in one project. `/api/*` rewrites to `/api/index`; development forwards to port 8000. The deployed project has a **free Neon PostgreSQL database in Singapore**, connected through Vercel's managed DATABASE_URL environment variable. Data persists across function instances. For a fresh deployment, set DATABASE_URL before first use. Without it, Vercel falls back to `/tmp/fingraph.db`, an ephemeral demo database that may reset or differ across instances; the interface warns about that state.

Alternative: deploy `render.yaml` with managed PostgreSQL and update the frontend API rewrite to that origin. Docker: set `POSTGRES_PASSWORD` and `JWT_SECRET_KEY`, then `docker compose -f infrastructure/docker-compose.yml up --build`. The named PostgreSQL volume persists data.

## Verification

```powershell
npm run build
npm run typecheck
python -m pytest backend/tests -q
```

## Scoring model

Version demo-1.0: risk 25%, horizon 15%, goal 15%, liquidity 15%, affordability 10%, fees 5%, preferences 5%, diversification 10%. Uses the lower of stated risk tolerance and capacity. Hard gates cover risk, liquidity, amount limits, horizon, exclusions, currency and product status. Gates override numeric scores. Missing mandatory data returns insufficient information or validation failure. Missing product-specific evidence prevents strong compatibility. ESG attributes require human verification. Diversification is disclosed as neutral 50/100 because holdings data is unavailable. These are educational parameters, not regulatory standards.

## Remaining limitations

This is a functional demonstration, not every enterprise capability in the master brief. Active graph backend is NetworkX, not Neo4j. Retrieval uses lexical cosine token vectors, not semantic embeddings/Chroma/Qdrant. No live market feed, live performance, OpenAI generation, persistent LangGraph checkpoints, background queue, workflow retry/cancellation UI, configurable-weight UI, user-management UI, or regulatory validation is included. The SQLAlchemy schema uses indexed JSON records and users rather than the full normalized 21-table Alembic design. Initial schema migration is idempotent creation, not an alter migration framework.

Authentication rate limiting is process-local. Cookies use same-site protection; add explicit CSRF protection, distributed rate limits and an independent security review before sensitive production use. Public demo reviewers share a demo identity and do not identify real people. Investor deletion removes related assessments/history; previously generated report references can then become unavailable. This platform does not provide licensed advice, guarantee returns or execute transactions. Protected demographic fields are excluded from scoring.
