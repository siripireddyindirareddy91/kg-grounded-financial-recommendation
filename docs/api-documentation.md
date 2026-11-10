# API and trust boundaries

Authoritative schema: `/api/docs`, JSON `/api/openapi.json`. All business endpoints require an authenticated JWT session. Viewer accounts are read-only; analyst/reviewer/admin roles guard mutations. Product writes and audit access require admin. Human decisions require reviewer or admin.

Browser → same-origin Next.js API rewrite → FastAPI → SQLAlchemy → SQLite locally or managed PostgreSQL. A graph is derived from stable investor/product IDs before scoring. Product-specific chunks are retrieved from uploaded/seeded documents. LangGraph passes structured state through ten operations. Hard constraints precede ranking. Review decisions are separate authenticated actions.

Auth: POST `/api/auth/demo`, `/register`, `/login`, `/logout`; GET `/api/auth/me`. Investors/products: GET/POST collections and GET/PUT/DELETE by ID; collection text search, product category/risk and offset/limit pagination. Assessments: POST with investor_id, GET collection/by ID, POST by-ID `/run`. Recommendations and agents reuse the workflow. Graph supports GET with q and POST query label searches, not arbitrary Cypher.

Documents support multipart upload, list/detail/delete, reindex and POST search query. Reports support generate with assessment_id and download with format csv/pdf. Human review: POST `/api/reviews/{id}/decision` with decision and required comment. Analytics accepts days/category filters. Health identifies active providers and durability.

Errors use `detail`: 401 unauthenticated, 403 unauthorized, 404 missing, 409 duplicate, 413 upload too large, 422 invalid data, 429 too many authentication requests.
