# Checklist CL-04 — Health, Logs, CORS, API Docs

| Field | Value |
|---|---|
| Module | F-11 Health check, F-13 Logging, F-14 CORS, F-15 API documentation from the [Test Plan](../TEST_PLAN.md) |
| Product version | API v1.7.0 |
| Environment | Local (Docker), `http://localhost:8000` |
| Executed by | |
| Run date | |

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
| HL-01 | Request with API and DB running | `200`, `{"status": "ok", "database": "ok"}` | H | | |
| HL-02 | Access without authorization | `200`: public endpoint | H | | |
| HL-03 | With any `Authorization` (invalid token) | `200`: the token is ignored | L | | |
| HL-04 | Response structure and types | Exactly two string fields `status` and `database`; `Content-Type: application/json` | M | | |
| HL-05 | The response does not expose sensitive data | No software versions, connection string, DB host name, environment variables | H | | |
| HL-06 | Response time | ❓ < 200 ms on the local stand (health is polled often by monitoring) | L | | |
| HL-07 | `HEAD /health` method | ❓ `200` without a body: some monitoring systems use `HEAD`. Record the actual response | L | | |
| HL-08 | Unsupported methods (`POST`, `DELETE`) | `405 Method Not Allowed` | L | | |
| HL-09 | Path `/health/` (trailing slash) | `307` redirect to `/health` or `404`. Record | L | | |

### 1.2 Database failure

> Stop the database: `docker compose stop db`. Restore after the section: `docker compose start db`.

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| HL-10 | `GET /health` with the DB stopped | `"database": "error"`; the response arrives without hanging | H | | |
| HL-11 | HTTP code with the DB unavailable | ❓ `503 Service Unavailable`: load balancers and monitoring rely on the code, not the body. If `200` is returned, monitoring will not see the problem — record | H | | |
| HL-12 | `status` field with the DB unavailable | ❓ `"status"` reflects the overall failure (`"error"` / `"degraded"`), not `"ok"` | M | | |
| HL-13 | Response time with the DB unavailable | ❓ Response within a reasonable timeout (< 5 s), not after a long connection wait | M | | |
| HL-14 | DB error text is not in the response | The response contains only `"error"`, no exception text | M | | |
| HL-15 | Other endpoints with the DB unavailable (`POST /users/login`) | ❓ `503` / `500` with a generic message, no stack trace or connection details | M | | |
| HL-16 | Recovery | `docker compose start db` → `GET /health` → `"database": "ok"` without restarting the API | H | | |

### 1.3 Application startup

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| HL-17 | Migrations on startup | API logs contain `Migrations completed successfully`; `SELECT version_num FROM alembic_version;` = the latest revision (`alembic heads`) | M | | |
| HL-18 | API startup with the DB unavailable | ❓ Stop `db` → `docker compose restart api`. Record: does the app fail with a clear error, does it start without migrations | L | | |
| HL-19 | Cold start: `docker compose down -v && docker compose up` | A clean DB is created, migrations are applied, `GET /health` → `"database": "ok"` | M | | |
| HL-20 | DB schema matches the models | ❓ `\d users`, `\d items`, `\d refresh_tokens`, `\d logs` match `app/models.py`; `alembic check` finds no differences | L | | |

---

## 2. Logging (F-13)

> Logging is dual: to the container console (JSON) and to the `logs` table. Query for checks: `SELECT id, level, message, user_id, path, method, status_code, duration_ms, ip, created_at FROM logs ORDER BY id DESC LIMIT 10;`

### 2.1 Event coverage (`logs` table)

> Perform the action → check the latest record in `logs`. Expected values are taken from the README and the source code.

| ID | Event | Expected record in `logs` | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-01 | Successful registration | `INFO`, `path = /users/register`, `user_id` of the new user | M | | |
| LG-02 | Registration with an existing email | `WARNING`, `path = /users/register` | M | | |
| LG-03 | Successful login | `INFO`, `path = /users/login`, `user_id` | H | | |
| LG-04 | Login with a wrong password | `WARNING`, `user_id` of the user (important for attack investigation) | H | | |
| LG-05 | Login with a non-existent email | `WARNING`, `user_id = NULL` | M | | |
| LG-06 | Successful refresh | `INFO`, `path = /users/refresh`, `user_id` | M | | |
| LG-07 | Refresh with an invalid token | `WARNING`, `path = /users/refresh` | M | | |
| LG-08 | Logout | `INFO`, `path = /users/logout`; ❓ `user_id` set | L | | |
| LG-09 | Logout-all | `INFO`, `path = /users/logout-all`, `user_id` | L | | |
| LG-10 | Item created | `INFO`, `item_created`, `method = POST`, `status_code = 201`, `user_id` | M | | |
| LG-11 | Item updated | `INFO`, `item_updated`, `method = PUT`, `status_code = 200`, `path = /items/{id}` | M | | |
| LG-12 | Item deleted | `INFO`, `item_deleted`, `method = DELETE`, `status_code = 204` | M | | |
| LG-13 | Update / Delete of a non-existent item | `WARNING`, `item_not_found`, `status_code = 404` | L | | |
| LG-14 | Update / Delete of someone else's item | `WARNING`, `item_update_forbidden` / `item_delete_forbidden`, `status_code = 403`, `user_id` of the offender | H | | |
| LG-15 | Request with an invalid access token (`401`) | ❓ Record whether it is logged (access attempts with forged tokens matter for security) | M | | |
| LG-16 | Validation error (`422`) | ❓ Record whether it is logged | L | | |
| LG-17 | Rate limit exceeded (`429`) | ❓ Record whether it is logged (see RL-39) | L | | |
| LG-18 | `GET /items/`, `GET /items/all`, `GET /health` | ❓ Record whether read operations are logged. Absence is fine if intended | L | | |
| LG-19 | Server error (`500`, e.g. with the DB unavailable) | ❓ An `ERROR` record in the console (it cannot be written to the DB) | M | | |

### 2.2 Field quality and completeness

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-20 | `ip` field | ❓ Filled with the client IP for all records. Without the IP attacks cannot be investigated. Record the share of filled records | M | | R-12 |
| LG-21 | `duration_ms` field | ❓ Filled with the request processing time. Record the share of filled records | L | | R-12 |
| LG-22 | `method` and `status_code` fields | ❓ Filled consistently for all events (both users and items). Compare LG-01…LG-09 with LG-10…LG-14 | M | | R-12 |
| LG-23 | `status_code` matches the actual response code | For each record `status_code` = the code the client received | M | | |
| LG-24 | Consistent `message` format | ❓ Users use free text with email, items use event codes (`item_created`). Record the inconsistency | L | | |
| LG-25 | `level` — only allowed values | `INFO`, `WARNING`, `ERROR` in upper case | L | | |
| LG-26 | `created_at` | Set, in UTC, ≈ request time; records are ordered by time | L | | |
| LG-27 | One action — one record | No duplicate records for one request | L | | |

### 2.3 Log security

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-28 | Passwords do not get into logs | After registrations and logins (successful and failed): `SELECT * FROM logs WHERE message ILIKE '%<password>%';` → 0 rows; none in the console either | H | | |
| LG-29 | Tokens do not get into logs | Neither access nor refresh tokens nor their hashes appear in `logs` or in the console | H | | |
| LG-30 | Email (PII) in logs | ❓ Emails are stored in `message` in plain text. Record as a remark (GDPR, masking `u***@test.com`) | M | | R-12 |
| LG-31 | Emails of non-existent users in logs | ❓ On a failed login any email typed by anyone is logged. Check with an email like `"<script>@x.com"` and a long email: the record is not broken | L | | |
| LG-32 | Log injection | Registration / login with an email containing `\n` or a JSON fragment (if it passes validation): the console log stays valid single-line JSON, no fake record is created | L | | |
| LG-33 | Retention and rotation | ❓ The `logs` table grows without limit. Clarify the retention policy | L | | |

### 2.4 Console JSON log

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LG-34 | Line format | Each application log line is valid JSON (check: `docker compose logs --no-log-prefix api \| grep '"level"' \| python -m json.tool --json-lines`) | M | | |
| LG-35 | Mandatory fields | `time` (ISO 8601, UTC), `level`, `message` | M | | |
| LG-36 | Additional fields | `user_id`, `path`, `method`, `status_code` are present when passed; empty ones are omitted | L | | |
| LG-37 | Console and DB consistency | For one event `level`, `message`, `user_id` match in the console and in `logs` | L | | |
| LG-38 | uvicorn logs (access log) | ❓ uvicorn lines are not JSON — record the mixed formats in one stream | L | | |

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
| CR-01 | Preflight `OPTIONS /items/` with `Origin: http://localhost:3000`, method `POST` | `200`; `Access-Control-Allow-Origin: http://localhost:3000`; `Access-Control-Allow-Credentials: true`; `Access-Control-Allow-Methods` contains `POST` | H | | |
| CR-02 | Preflight with `Access-Control-Request-Headers: Authorization, Content-Type` | `Access-Control-Allow-Headers` contains both headers | H | | |
| CR-03 | Preflight for `PUT` and `DELETE` (`/items/1`) | `200`, methods allowed | M | | |
| CR-04 | Regular `GET /health` with the allowed `Origin` | `Access-Control-Allow-Origin: http://localhost:3000`, `Access-Control-Allow-Credentials: true` | H | | |
| CR-05 | `POST /users/login` with the allowed `Origin` | CORS headers + `Set-Cookie` in the response | H | | |
| CR-06 | `Allow-Origin` with `allow_credentials = true` | Never `*`, always the specific origin | H | | |
| CR-07 | `Vary: Origin` header | Present (correct caching) | L | | |
| CR-08 | `Access-Control-Max-Age` | ❓ Present (default `600`). Record the value | L | | |

### 3.2 Disallowed origins and methods

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CR-09 | Preflight with `Origin: http://evil.com` | `400` (`Disallowed CORS origin`), no `Access-Control-Allow-Origin` | H | | |
| CR-10 | Regular `GET /health` with `Origin: http://evil.com` | `200` is returned, but **without** `Access-Control-Allow-Origin` (the browser blocks reading it) | H | | |
| CR-11 | Look-alike origins: `https://localhost:3000`, `http://localhost:3001`, `http://127.0.0.1:3000`, `http://localhost:3000.evil.com`, `http://evil.com/http://localhost:3000` | None is allowed | H | | |
| CR-12 | `Origin: null` | Not allowed | M | | |
| CR-13 | `Origin: http://LOCALHOST:3000` (case) | ❓ Record the behaviour | L | | |
| CR-14 | Preflight with method `PATCH` | `400`, `PATCH` not in `Allow-Methods` | M | | |
| CR-15 | Preflight with an arbitrary header `X-Custom: 1` | Allowed (`allow_headers = *`). ❓ Record as an overly broad setting | L | | |

### 3.3 CORS with errors and other cases

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CR-16 | `401` response with the allowed `Origin` | CORS headers present (otherwise the frontend cannot read the error) | M | | |
| CR-17 | `429` response with the allowed `Origin` | CORS headers present | M | | |
| CR-18 | `500` response (DB stopped) with the allowed `Origin` | ❓ Record whether CORS headers are present. Without them the browser shows a CORS error instead of the server error | L | | |
| CR-19 | Are preflight requests counted by the rate limit | ❓ 110 × `OPTIONS /health` → record whether `429` comes | L | | |
| CR-20 | Browser check | From `http://localhost:3000` fetch succeeds; from `http://localhost:8080` (`python3 -m http.server 8080`) — CORS error in the console | M | | |
| CR-21 | Request without `Origin` (curl, Postman) | Processed normally. This is expected: CORS protects the browser, not the server | L | | |
| CR-22 | Origin configuration (code analysis) | ❓ Only `http://localhost:3000` is allowed, the origin is hardcoded in `main.py` instead of `.env`. Any other environment needs a new release — record as a remark | M | | R-15 |

---

## 4. API documentation (F-15)

### 4.1 Availability

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-01 | `GET /docs` | Swagger UI loads without errors in the browser console | M | | |
| DOC-02 | `GET /redoc` | ReDoc loads | L | | |
| DOC-03 | `GET /openapi.json` | `200`, valid JSON; the spec passes validation (e.g. editor.swagger.io → File → Import) | M | | |

### 4.2 Content

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-04 | All endpoints from the README are present | 11 endpoints grouped by tags `Users`, `Items`, `Health` | M | | |
| DOC-05 | Version | `info.version` = `1.7.0`; matches README / Roadmap | L | | |
| DOC-06 | Endpoint descriptions | Every endpoint has a `summary` and a description. ❓ Items endpoints have none — record (Roadmap v1.7: "Swagger descriptions per endpoint" is marked done) | L | | |
| DOC-07 | Documented response codes | Every code in the description is reproducible (cross-check with CL-01 SEC-10, CL-02 CTR-03) | M | | R-06 |
| DOC-08 | Response schemas | ❓ Endpoints declare response schemas (`response_model`), not an empty `{}` | M | | R-05 |
| DOC-09 | Pagination parameter description | `page`, `limit`: type, defaults; ❓ min/max constraints | L | | |
| DOC-10 | Field constraints in schemas | ❓ Constraints (e.g. password min 6) are reflected in the schema (`minLength`), not only in the description text | L | | R-01 |
| DOC-11 | Security scheme | `HTTPBearer` is described; protected endpoints show a lock | M | | |
| DOC-12 | **Authorize** button | After entering a token, items requests from Swagger UI return `200` | M | | |
| DOC-13 | Refresh / Logout from Swagger UI | ❓ Cookie auth is not described in Swagger — record whether these endpoints can be tested via the UI | L | | |
| DOC-14 | Contact and license | `contact` and `license` are set, the repository link works | L | | |

### 4.3 Consistency with the README

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DOC-15 | Endpoint table in the README | Methods, paths and auth flag match `/openapi.json` and actual behaviour | L | | |
| DOC-16 | Environment variables in the README | The list and defaults match `app/config.py` and `.env.example` | L | | |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Health check | 20 | | | | |
| 2. Logging | 38 | | | | |
| 3. CORS | 22 | | | | |
| 4. API documentation | 16 | | | | |
| **Total** | **96** | | | | |

**Defects found:**

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| | | | |

**Questions to the developer (❓ checks):**

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| | | | |
