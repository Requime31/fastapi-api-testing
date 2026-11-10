# Checklist CL-04 — Health, Logs, CORS, API Docs

| Field | Value |
|---|---|
| Module | F-11 Health check, F-13 Logging, F-14 CORS, F-15 API documentation from the [Test Plan](../TEST_PLAN.md) |
| Product version | API v1.7.0 |
| Environment | Local (Docker), `http://localhost:8000` |
| Executed by | QA (Requime31); executed with [`qa/scripts/run_cl04_health_logs_cors.py`](../../qa/scripts/run_cl04_health_logs_cors.py) |
| Run date | 10.11.2026 · build `660708b` · raw results [`qa/runs/CL-04_2026-11-10.json`](../../qa/runs/CL-04_2026-11-10.json) · Jira FAT-6 ([#6](https://github.com/Requime31/fastapi-api-testing/issues/6)) · CR-20 in Chrome (built-in browser) |

**Legend:**
- **Priority:** H — High, M — Medium, L — Low
- **Status:** ✅ Passed · ❌ Failed · ⚠️ Blocked · ⏭ Skipped
- **❓** — the requirement is not explicitly documented; the expected result is based on common practice; on mismatch, file a question / bug
- **R-xx** — reference to a risk area in the Test Plan

**Preconditions for the whole module:**
1. The stand is started with `qa/docker-compose.functional.yml` (limits `1000/minute`; rate limiting is tested in [CL-03](CL-03_RateLimit.md)).
2. Database access is open: `docker exec -it fastapi_postgres psql -U postgres -d fastapi_db`.
3. Container logs are open in a separate terminal: `docker compose logs -f api`.

---

## 1. Health check — `GET /health` (F-11)

### 1.1 Normal operation

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| HL-01 | Request with API and DB running | `200`, `{"status": "ok", "database": "ok"}` | ✅ | |
| HL-02 | Access without authorization | `200`: public endpoint | ✅ | |
| HL-03 | With any `Authorization` (invalid token) | `200`: the token is ignored | ✅ | |
| HL-04 | Response structure and types | Exactly two string fields `status` and `database`; `Content-Type: application/json` | ✅ | |
| HL-05 | The response does not expose sensitive data | No software versions, connection string, DB host name, environment variables | ✅ | no versions or connection details in the body |
| HL-06 | Response time | ❓ < 200 ms on the local stand (health is polled often by monitoring) | ✅ | |
| HL-07 | `HEAD /health` method | ❓ `200` without a body: some monitoring systems use `HEAD`. Record the actual response | ❌ | Actual: HEAD /health → 405 → **[FAT-40](https://github.com/Requime31/fastapi-api-testing/issues/40)** |
| HL-08 | Unsupported methods (`POST`, `DELETE`) | `405 Method Not Allowed` | ✅ | |
| HL-09 | Path `/health/` (trailing slash) | `307` redirect to `/health` or `404`. Record | ✅ | |

### 1.2 Database failure

> Stop the database: `docker compose stop db`. Restore after the section: `docker compose start db`.

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| HL-10 | `GET /health` with the DB stopped | `"database": "error"`; the response arrives without hanging | ✅ | |
| HL-11 | HTTP code with the DB unavailable | ❓ `503 Service Unavailable`: load balancers and monitoring rely on the code, not the body. If `200` is returned, monitoring will not see the problem — record | ❌ | Actual: HTTP 200 → **[FAT-39](https://github.com/Requime31/fastapi-api-testing/issues/39)** |
| HL-12 | `status` field with the DB unavailable | ❓ `"status"` reflects the overall failure (`"error"` / `"degraded"`), not `"ok"` | ❌ | Actual: status = ok → **[FAT-39](https://github.com/Requime31/fastapi-api-testing/issues/39)** |
| HL-13 | Response time with the DB unavailable | ❓ Response within a reasonable timeout (< 5 s), not after a long connection wait | ✅ | |
| HL-14 | DB error text is not in the response | The response contains only `"error"`, no exception text | ✅ | |
| HL-15 | Other endpoints with the DB unavailable (`POST /users/login`) | ❓ `503` / `500` with a generic message, no stack trace or connection details | ✅ | |
| HL-16 | Recovery | `docker compose start db` → `GET /health` → `"database": "ok"` without restarting the API | ✅ | |

### 1.3 Application startup

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| HL-17 | Migrations on startup | API logs contain `Migrations completed successfully`; `SELECT version_num FROM alembic_version;` = the latest revision (`alembic heads`) | ❌ | Actual: alembic_version table exists: False, version=None, head=08621c7ff5c6; manual `alembic upgrade head` → exit 1: sqlalchemy.exc.Prog… → **[FAT-37](https://github.com/Requime31/fastapi-api-testing/issues/37)** |
| HL-18 | API startup with the DB unavailable | ❓ Stop `db` → `docker compose restart api`. Record: does the app fail with a clear error, does it start without migrations | ✅ | the app crashes on startup (create_all fails) and the container stays down until restarted manually; stand restored: True |
| HL-19 | Cold start: `docker compose down -v && docker compose up` | A clean DB is created, migrations are applied, `GET /health` → `"database": "ok"` | ❌ | Actual: fresh stack with an empty volume: /health ok=True after 4 s, tables=4, alembic_version=none; last migration step in the log: api-… → **[FAT-37](https://github.com/Requime31/fastapi-api-testing/issues/37)** |
| HL-20 | DB schema matches the models | ❓ `\d users`, `\d items`, `\d refresh_tokens`, `\d logs` match `app/models.py`; `alembic check` finds no differences | ❌ | Actual: alembic check → exit 255: ERROR [alembic.util.messaging] Target database is not up to date. → **[FAT-37](https://github.com/Requime31/fastapi-api-testing/issues/37)** |

---

## 2. Logging (F-13)

> Logging is dual: to the container console (JSON) and to the `logs` table. Query for checks: `SELECT id, level, message, user_id, path, method, status_code, duration_ms, ip, created_at FROM logs ORDER BY id DESC LIMIT 10;`

### 2.1 Event coverage (`logs` table)

> Perform the action → check the latest record in `logs`. Expected values are taken from the README and the source code.

| ID | Event | Expected record in `logs` | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-01 | Successful registration | `INFO`, `path = /users/register`, `user_id` of the new user | ✅ | |
| LG-02 | Registration with an existing email | `WARNING`, `path = /users/register` | ✅ | |
| LG-03 | Successful login | `INFO`, `path = /users/login`, `user_id` | ✅ | |
| LG-04 | Login with a wrong password | `WARNING`, `user_id` of the user (important for attack investigation) | ✅ | |
| LG-05 | Login with a non-existent email | `WARNING`, `user_id = NULL` | ✅ | |
| LG-06 | Successful refresh | `INFO`, `path = /users/refresh`, `user_id` | ✅ | |
| LG-07 | Refresh with an invalid token | `WARNING`, `path = /users/refresh` | ✅ | |
| LG-08 | Logout | `INFO`, `path = /users/logout`; ❓ `user_id` set | ❌ | Actual: ['INFO', 'User logged out', 'NULL'] → **[FAT-19](https://github.com/Requime31/fastapi-api-testing/issues/19)** |
| LG-09 | Logout-all | `INFO`, `path = /users/logout-all`, `user_id` | ✅ | |
| LG-10 | Item created | `INFO`, `item_created`, `method = POST`, `status_code = 201`, `user_id` | ✅ | |
| LG-11 | Item updated | `INFO`, `item_updated`, `method = PUT`, `status_code = 200`, `path = /items/{id}` | ✅ | |
| LG-12 | Item deleted | `INFO`, `item_deleted`, `method = DELETE`, `status_code = 204` | ✅ | |
| LG-13 | Update / Delete of a non-existent item | `WARNING`, `item_not_found`, `status_code = 404` | ✅ | |
| LG-14 | Update / Delete of someone else's item | `WARNING`, `item_update_forbidden` / `item_delete_forbidden`, `status_code = 403`, `user_id` of the offender | ✅ | |
| LG-15 | Request with an invalid access token (`401`) | ❓ Record whether it is logged (access attempts with forged tokens matter for security) | ❌ | Actual: request with an invalid token → new log records: 0 → **[FAT-36](https://github.com/Requime31/fastapi-api-testing/issues/36)** |
| LG-16 | Validation error (`422`) | ❓ Record whether it is logged | ✅ | validation errors are not logged (acceptable) |
| LG-17 | Rate limit exceeded (`429`) | ❓ Record whether it is logged (see RL-39) | ❌ | Actual: see CL-03 RL-39: rate limit violations are not written to logs or the console → **[FAT-36](https://github.com/Requime31/fastapi-api-testing/issues/36)** |
| LG-18 | `GET /items/`, `GET /items/all`, `GET /health` | ❓ Record whether read operations are logged. Absence is fine if intended | ✅ | read operations are not logged (acceptable) |
| LG-19 | Server error (`500`, e.g. with the DB unavailable) | ❓ An `ERROR` record in the console (it cannot be written to the DB) | ❌ | Actual: console lines during the DB outage: ERROR/Exception lines 0, structured JSON ERROR: False → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |

### 2.2 Field quality and completeness

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-20 | `ip` field | ❓ Filled with the client IP for all records. Without the IP attacks cannot be investigated. Record the share of filled records | ❌ | Actual: records with ip: 0 of 1562 → **[FAT-41](https://github.com/Requime31/fastapi-api-testing/issues/41)** R-12 |
| LG-21 | `duration_ms` field | ❓ Filled with the request processing time. Record the share of filled records | ❌ | Actual: records with duration_ms: 0 of 1562 → **[FAT-41](https://github.com/Requime31/fastapi-api-testing/issues/41)** R-12 |
| LG-22 | `method` and `status_code` fields | ❓ Filled consistently for all events (both users and items). Compare LG-01…LG-09 with LG-10…LG-14 | ❌ | Actual: auth records with method/status_code: 0 of 1019; items records: always set → **[FAT-41](https://github.com/Requime31/fastapi-api-testing/issues/41)** R-12 |
| LG-23 | `status_code` matches the actual response code | For each record `status_code` = the code the client received | ✅ | |
| LG-24 | Consistent `message` format | ❓ Users use free text with email, items use event codes (`item_created`). Record the inconsistency | ❌ | Actual: message styles: free text with email ("User logged in: user@…") vs event codes (All sessions revoked for user_id: 132, Invalid or… → **[FAT-41](https://github.com/Requime31/fastapi-api-testing/issues/41)** |
| LG-25 | `level` — only allowed values | `INFO`, `WARNING`, `ERROR` in upper case | ✅ | |
| LG-26 | `created_at` | Set, in UTC, ≈ request time; records are ordered by time | ✅ | |
| LG-27 | One action — one record | No duplicate records for one request | ✅ | |

### 2.3 Log security

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-28 | Passwords do not get into logs | After registrations and logins (successful and failed): `SELECT * FROM logs WHERE message ILIKE '%<password>%';` → 0 rows; none in the console either | ✅ | |
| LG-29 | Tokens do not get into logs | Neither access nor refresh tokens nor their hashes appear in `logs` or in the console | ✅ | |
| LG-30 | Email (PII) in logs | ❓ Emails are stored in `message` in plain text. Record as a remark (GDPR, masking `u***@test.com`) | ❌ | Actual: records of this run containing an email: 10 → **[FAT-17](https://github.com/Requime31/fastapi-api-testing/issues/17)** R-12 |
| LG-31 | Emails of non-existent users in logs | ❓ On a failed login any email typed by anyone is logged. Check with an email like `"<script>@x.com"` and a long email: the record is not broken | ✅ | invalid emails are rejected by validation before logging, so arbitrary strings cannot reach the log |
| LG-32 | Log injection | Registration / login with an email containing `\n` or a JSON fragment (if it passes validation): the console log stays valid single-line JSON, no fake record is created | ✅ | rejected by email validation |
| LG-33 | Retention and rotation | ❓ The `logs` table grows without limit. Clarify the retention policy | ❌ | Actual: logs table: 1563 rows since 2026-11-05 14:15:27.205972; no retention / cleanup in the code → **[FAT-50](https://github.com/Requime31/fastapi-api-testing/issues/50)** |

### 2.4 Console JSON log

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-34 | Line format | Each application log line is valid JSON (check: `docker compose logs --no-log-prefix api \| grep '"level"' \| python -m json.tool --json-lines`) | ❌ | Actual: container log: 165 lines in total, JSON lines: 0, invalid: 0 → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |
| LG-35 | Mandatory fields | `time` (ISO 8601, UTC), `level`, `message` | ❌ | Actual: JSON lines to check: 0 → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |
| LG-36 | Additional fields | `user_id`, `path`, `method`, `status_code` are present when passed; empty ones are omitted | ❌ | Actual: item_created line in the console: None → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |
| LG-37 | Console and DB consistency | For one event `level`, `message`, `user_id` match in the console and in `logs` | ❌ | Actual: console None vs DB ('INFO', '132') → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |
| LG-38 | uvicorn logs (access log) | ❓ uvicorn lines are not JSON — record the mixed formats in one stream | ❌ | Actual: non-JSON lines in the stream: 165 (e.g. INFO  [alembic.runtime.migration] Running upgrade 2317e5de5f12 -> 1244) → **[FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38)** |

---

## 3. CORS (F-14)

> Configuration: `allow_origins = ["http://localhost:3000"]`, `allow_credentials = True`, `allow_methods = GET, POST, PUT, DELETE`, `allow_headers = *`.
>
> CORS headers are checked with Postman or curl by adding an `Origin` header. Example preflight request:
> ```bash
> curl -i -X OPTIONS http://localhost:8000/items/ \
>   -H "Origin: http://localhost:3000" \
>   -H "Access-Control-Request-Method: POST" \
>   -H "Access-Control-Request-Headers: Authorization, Content-Type"
> ```
> For a check in a real browser (CR-20): `python3 -m http.server 3000` in an empty folder → open `http://localhost:3000` → run in the DevTools console: `fetch("http://localhost:8000/health").then(r => r.json()).then(console.log)`.

### 3.1 Allowed origin

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CR-01 | Preflight `OPTIONS /items/` with `Origin: http://localhost:3000`, method `POST` | `200`; `Access-Control-Allow-Origin: http://localhost:3000`; `Access-Control-Allow-Credentials: true`; `Access-Control-Allow-Methods` contains `POST` | ✅ | |
| CR-02 | Preflight with `Access-Control-Request-Headers: Authorization, Content-Type` | `Access-Control-Allow-Headers` contains both headers | ✅ | |
| CR-03 | Preflight for `PUT` and `DELETE` (`/items/1`) | `200`, methods allowed | ✅ | |
| CR-04 | Regular `GET /health` with the allowed `Origin` | `Access-Control-Allow-Origin: http://localhost:3000`, `Access-Control-Allow-Credentials: true` | ✅ | |
| CR-05 | `POST /users/login` with the allowed `Origin` | CORS headers + `Set-Cookie` in the response | ✅ | |
| CR-06 | `Allow-Origin` with `allow_credentials = true` | Never `*`, always the specific origin | ✅ | |
| CR-07 | `Vary: Origin` header | Present (correct caching) | ✅ | |
| CR-08 | `Access-Control-Max-Age` | ❓ Present (default `600`). Record the value | ✅ | |

### 3.2 Disallowed origins and methods

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CR-09 | Preflight with `Origin: http://evil.com` | `400` (`Disallowed CORS origin`), no `Access-Control-Allow-Origin` | ✅ | |
| CR-10 | Regular `GET /health` with `Origin: http://evil.com` | `200` is returned, but **without** `Access-Control-Allow-Origin` (the browser blocks reading it) | ✅ | |
| CR-11 | Look-alike origins: `https://localhost:3000`, `http://localhost:3001`, `http://127.0.0.1:3000`, `http://localhost:3000.evil.com`, `http://evil.com/http://localhost:3000` | None is allowed | ✅ | |
| CR-12 | `Origin: null` | Not allowed | ✅ | |
| CR-13 | `Origin: http://LOCALHOST:3000` (case) | ❓ Record the behaviour | ✅ | origin matching is case-sensitive |
| CR-14 | Preflight with method `PATCH` | `400`, `PATCH` not in `Allow-Methods` | ✅ | |
| CR-15 | Preflight with an arbitrary header `X-Custom: 1` | Allowed (`allow_headers = *`). ❓ Record as an overly broad setting | ✅ | allow_headers=* accepts any request header — broader than needed (Authorization, Content-Type) |

### 3.3 CORS with errors and other cases

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CR-16 | `401` response with the allowed `Origin` | CORS headers present (otherwise the frontend cannot read the error) | ✅ | |
| CR-17 | `429` response with the allowed `Origin` | CORS headers present | ✅ | |
| CR-18 | `500` response (DB stopped) with the allowed `Origin` | ❓ Record whether CORS headers are present. Without them the browser shows a CORS error instead of the server error | ❌ | Actual: 500 (DB down, HL-15) with the allowed Origin → ACAO=None → **[FAT-42](https://github.com/Requime31/fastapi-api-testing/issues/42)** |
| CR-19 | Are preflight requests counted by the rate limit | ❓ 110 × `OPTIONS /health` → record whether `429` comes | ✅ | preflight requests are answered by CORSMiddleware before the rate limiter |
| CR-20 | Browser check | From `http://localhost:3000` fetch succeeds; from `http://localhost:8080` (`python3 -m http.server 8080`) — CORS error in the console | ✅ | |
| CR-21 | Request without `Origin` (curl, Postman) | Processed normally. This is expected: CORS protects the browser, not the server | ✅ | |
| CR-22 | Origin configuration (code analysis) | ❓ Only `http://localhost:3000` is allowed, the origin is hardcoded in `main.py` instead of `.env`. Any other environment needs a new release — record as a remark | ❌ | Actual: app/main.py: allow_origins=["http://localhost:3000"] (hardcoded) → **[FAT-43](https://github.com/Requime31/fastapi-api-testing/issues/43)** R-15 |

---

## 4. API documentation (F-15)

### 4.1 Availability

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-01 | `GET /docs` | Swagger UI loads without errors in the browser console | ✅ | |
| DOC-02 | `GET /redoc` | ReDoc loads | ✅ | |
| DOC-03 | `GET /openapi.json` | `200`, valid JSON; the spec passes validation (e.g. editor.swagger.io → File → Import) | ✅ | |

### 4.2 Content

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-04 | All endpoints from the README are present | 11 endpoints grouped by tags `Users`, `Items`, `Health` | ✅ | |
| DOC-05 | Version | `info.version` = `1.7.0`; matches README / Roadmap | ✅ | |
| DOC-06 | Endpoint descriptions | Every endpoint has a `summary` and a description. ❓ Items endpoints have none — record (Roadmap v1.7: "Swagger descriptions per endpoint" is marked done) | ❌ | Actual: operations without a description: ['DELETE /items/{item_id}', 'GET /items/', 'GET /items/all', 'POST /items/', 'PUT /items/{item_… → **[FAT-30](https://github.com/Requime31/fastapi-api-testing/issues/30)** |
| DOC-07 | Documented response codes | Every code in the description is reproducible (cross-check with CL-01 SEC-10, CL-02 CTR-03) | ❌ | Actual: login: 200/401/404 reproduced; logout-all documents 401 but returns 403 without a token (FAT-13); refresh/logout document an unre… → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13), [FAT-22](https://github.com/Requime31/fastapi-api-testing/issues/22)** R-06 |
| DOC-08 | Response schemas | ❓ Endpoints declare response schemas (`response_model`), not an empty `{}` | ❌ | Actual: operations whose success response schema is empty: ['DELETE /items/{item_id}', 'GET /health', 'GET /items/', 'GET /items/all', 'P… → **[FAT-30](https://github.com/Requime31/fastapi-api-testing/issues/30)** R-05 |
| DOC-09 | Pagination parameter description | `page`, `limit`: type, defaults; ❓ min/max constraints | ❌ | Actual: /items/all params: {'page': {'type': 'integer', 'default': 1, 'title': 'Page'}, 'limit': {'type': 'integer', 'default': 10, 'titl… → **[FAT-30](https://github.com/Requime31/fastapi-api-testing/issues/30)** |
| DOC-10 | Field constraints in schemas | ❓ Constraints (e.g. password min 6) are reflected in the schema (`minLength`), not only in the description text | ❌ | Actual: UserCreate.password schema: {'type': 'string', 'title': 'Password'} → **[FAT-8](https://github.com/Requime31/fastapi-api-testing/issues/8)** R-01 |
| DOC-11 | Security scheme | `HTTPBearer` is described; protected endpoints show a lock | ✅ | |
| DOC-12 | **Authorize** button | After entering a token, items requests from Swagger UI return `200` | ✅ | verified at the API level; the Authorize dialog itself was checked in the browser |
| DOC-13 | Refresh / Logout from Swagger UI | ❓ Cookie auth is not described in Swagger — record whether these endpoints can be tested via the UI | ✅ | refresh_token is documented as a cookie parameter, but Swagger UI cannot send cookie parameters — these endpoints work from the UI only with the cookie the browser received from /users/login |
| DOC-14 | Contact and license | `contact` and `license` are set, the repository link works | ✅ | |

### 4.3 Consistency with the README

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-15 | Endpoint table in the README | Methods, paths and auth flag match `/openapi.json` and actual behaviour | ✅ | |
| DOC-16 | Environment variables in the README | The list and defaults match `app/config.py` and `.env.example` | ❌ | Actual: variables required by docker-compose.yml but absent from the README table and .env.example (build 660708b): ['POSTGRES_DB', 'POST… → **[FAT-44](https://github.com/Requime31/fastapi-api-testing/issues/44)** |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Health check | 20 | 14 | 6 | 0 | 0 |
| 2. Logging | 38 | 23 | 15 | 0 | 0 |
| 3. CORS | 22 | 20 | 2 | 0 | 0 |
| 4. API documentation | 16 | 10 | 6 | 0 | 0 |
| **Total** | **96** | **67** | **29** | **0** | **0** |

Pass rate: **69.8%** (excluding ⏭). The module does not meet the exit criterion "≥ 95% passed".

**Defects found:**

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| [FAT-37](https://github.com/Requime31/fastapi-api-testing/issues/37) | HL-17, HL-19, HL-20 | Alembic migrations fail on every startup and the failure is silent: the initial migration is empty, the schema is created by `create_all`, `alembic_version` never exists | Major |
| [FAT-38](https://github.com/Requime31/fastapi-api-testing/issues/38) | LG-19, LG-34, LG-35, LG-36, LG-37, LG-38 | No application or uvicorn logs reach the console after startup: `fileConfig()` in `alembic/env.py` disables the existing loggers | Major |
| [FAT-39](https://github.com/Requime31/fastapi-api-testing/issues/39) | HL-11, HL-12 | `GET /health` returns `200` with `"status": "ok"` when the database is down | Major |
| [FAT-40](https://github.com/Requime31/fastapi-api-testing/issues/40) | HL-07 | `HEAD /health` returns `405` | Minor |
| [FAT-41](https://github.com/Requime31/fastapi-api-testing/issues/41) | LG-20, LG-21, LG-22, LG-24 | Log records are incomplete: `ip` and `duration_ms` are never filled, `method` / `status_code` are missing for auth events, two message formats | Minor |
| [FAT-36](https://github.com/Requime31/fastapi-api-testing/issues/36) | LG-15, LG-17 | Security events are not logged: failed authentication (invalid / forged token) and rate limit violations (429) leave no record | Minor |
| [FAT-42](https://github.com/Requime31/fastapi-api-testing/issues/42) | CR-18 | `500` responses carry no CORS headers — the browser shows a CORS error instead of the server error | Minor |
| [FAT-43](https://github.com/Requime31/fastapi-api-testing/issues/43) | CR-22 | Allowed CORS origins are hardcoded in `main.py` (`http://localhost:3000`) | Minor |
| [FAT-44](https://github.com/Requime31/fastapi-api-testing/issues/44) | DOC-16 | Setup docs: `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` required by `docker-compose.yml` are missing from the README and `.env.example` | Minor |
| [FAT-30](https://github.com/Requime31/fastapi-api-testing/issues/30) | DOC-06, DOC-08, DOC-09 | Swagger: items endpoints have no descriptions, no error codes (401/403/404) and no response schemas | Minor |

**Questions to the developer (❓ checks):**

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| [FAT-50](https://github.com/Requime31/fastapi-api-testing/issues/50) | LG-33 | The `logs` table grows without limit (no retention or cleanup). What is the retention policy? | |
