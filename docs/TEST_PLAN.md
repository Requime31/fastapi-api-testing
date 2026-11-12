# Test Plan — FastAPI Project (REST API)

| Field | Value |
|---|---|
| Document | Test Plan |
| Document version | 1.1 |
| Product version under test | API v1.7.0 (branch `master`, commit `660708b`) |
| Author | QA Engineer |
| Date | 06.11.2026 (updated 10.11.2026) |
| Status | Draft |

---

## 1. Introduction

### 1.1 Purpose
Define the scope, approach, resources, environments, criteria and schedule for testing the REST API of FastAPI Project. The document is the basis for checklists, test cases and the test summary report.

### 1.2 Product overview
A **FastAPI + PostgreSQL** backend service running in Docker. Source code: [nisanMan/fastapi-project](https://github.com/nisanMan/fastapi-project); a local copy is tested. Architecture:

```
Request → SlowAPI (rate limit) → CORS → Router → Service → Repository → DB
```

Key features:
- user registration and authentication (JWT access token + refresh token in an httpOnly cookie, refresh token rotation);
- logout from the current session and from all sessions;
- CRUD for the **Item** entity with ownership checks and soft delete;
- pagination of the list of all items;
- rate limiting (per IP);
- structured JSON logging persisted to the `logs` table;
- application and database health check;
- Alembic migrations on application startup.

### 1.3 Test basis
There is no formal specification, so requirements are reconstructed from:
- `README.md` (endpoints, auth flow, environment variables);
- Swagger / OpenAPI (`/docs`, `/openapi.json`) — endpoint descriptions and response codes;
- source code (`app/`) — actual behaviour;
- `tests/TESTING.md` — existing unit test coverage;
- results of the smoke test.

> Discrepancies between the documentation (README / Swagger) and actual behaviour are treated as defects — of the documentation or of the code — and filed in the bug tracker.

---

## 2. Scope

### 2.1 In scope

| ID | Module | Endpoint | Auth | Priority |
|---|---|---|---|---|
| F-01 | Registration | `POST /users/register` | — | High |
| F-02 | Login | `POST /users/login` | — | Critical |
| F-03 | Token refresh | `POST /users/refresh` | cookie | Critical |
| F-04 | Logout | `POST /users/logout` | cookie | High |
| F-05 | Logout from all devices | `POST /users/logout-all` | Bearer | High |
| F-06 | Create item | `POST /items/` | Bearer | High |
| F-07 | My items | `GET /items/` | Bearer | High |
| F-08 | All items (pagination) | `GET /items/all?page=&limit=` | Bearer | Medium |
| F-09 | Update item | `PUT /items/{item_id}` | Bearer | High |
| F-10 | Delete item (soft) | `DELETE /items/{item_id}` | Bearer | High |
| F-11 | Health check | `GET /health` | — | Medium |
| F-12 | Rate limiting | all endpoints | — | High |
| F-13 | Logging to DB | `logs` table | — | Medium |
| F-14 | CORS | all endpoints | — | Low |
| F-15 | API documentation | `/docs`, `/openapi.json` | — | Low |

### 2.2 Out of scope

| What | Reason |
|---|---|
| Email verification, password reset | Not implemented (Roadmap v1.6 `[~]`) |
| API versioning, metrics | Postponed to v2.0 |
| Redis, Nginx, background tasks | Not implemented (v2.0) |
| UI / frontend | None — the project is API only |
| Full load testing | No dedicated environment. A light rate limit check on the local stand is allowed |
| Author's production environment (Railway) | Someone else's service: testing without the owner's permission is not acceptable. All testing is done on the local stand only |
| CI/CD pipeline | DevOps responsibility; only checked that unit tests pass in CI |
| Third-party libraries (passlib, python-jose, slowapi) | Third-party code; only the integration is tested |

---

## 3. Test strategy

### 3.1 Test levels

| Level | What is tested | Who / how |
|---|---|---|
| Unit / Component | Services, repositories | Developer, pytest (exists, 96% coverage) |
| **API (integration)** | Endpoints over HTTP: contract, status codes, business logic | **QA — main focus**, Postman + Swagger + run scripts |
| **Database** | Data correctness after API operations | **QA**, psql |
| System / E2E | End-to-end scenarios (register → login → CRUD → logout) | QA, Postman Runner, run scripts |

### 3.2 Test types

| Type | Description | Applied to |
|---|---|---|
| Smoke | Basic operability of key endpoints | ✅ Done. Repeated on every new build |
| Functional (positive) | Valid data → expected result | All features F-01…F-11 |
| Functional (negative) | Invalid data, missing fields, wrong types, boundary values | All features with input |
| Contract | Responses match the OpenAPI schema: codes, JSON structure, field types, headers | All endpoints |
| Authorization and access control | Access without a token, with an expired / forged / revoked token, access to other users' resources (IDOR) | F-02…F-10 |
| Security (basic) | Password storage, cookie attributes, user enumeration, data leaks in responses and logs, SQL injection in input fields | Auth module, items |
| Rate limiting | Exceeding limits, 429 format, window reset | F-12 |
| Data (DB) | Records in `users`, `items`, `refresh_tokens`, `logs` after operations | F-01…F-13 |
| Regression | Re-run after defect fixes | Run scripts + Postman Collection + pytest |
| Confirmation (re-test) | Verifying the fix of a specific bug | Every fixed defect |

### 3.3 Test design techniques
- **Equivalence partitioning** — email, password, title/description, `page`, `limit`, `item_id`.
- **Boundary values** — password length (documented min 6 → 5 / 6 / 7), `page` and `limit` (−1 / 0 / 1 / large number), rate limits (N / N+1 requests).
- **Decision table** — permissions on item operations (owner / not owner / item deleted / item does not exist).
- **State transition** — refresh token lifecycle: `active → rotated (revoked) / revoked by logout / revoked by logout-all / expired`.
- **Pairwise testing** — combinations of pagination parameters.
- **Error guessing / exploratory testing** — based on code analysis and smoke test results.

### 3.4 Risk areas
Identified during code and documentation analysis. These are **hypotheses to verify**, not confirmed defects.

| # | Area | What to check | Risk |
|---|---|---|---|
| R-01 | Password validation | Swagger states "minimum 6 characters" — is it enforced? Empty password? | High |
| R-02 | Item field validation | Empty `title` / `description`, very long strings, special characters, unicode, HTML/JS | Medium |
| R-03 | Pagination `/items/all` | `page=0`, negative values, `limit=0`, non-numeric values, `page` greater than `pages` | High |
| R-04 | Soft delete | Do deleted items appear in `/items/` and `/items/all`? Are they counted in `total`? | High |
| R-05 | Response fields | Which item fields are returned (any internal fields)? Does the response match the `ItemResponse` schema? | Medium |
| R-06 | Response codes | Match with documented codes (`201`, `204`, `400`, `401`, `403`, `404`, `422`, `429`); does `204` have a body | Medium |
| R-07 | User enumeration | Do login responses differ for a non-existent user and a wrong password? | Medium |
| R-08 | Token lifecycle | Does the access token work after logout / logout-all? What does logout do with an invalid cookie? Reuse of an old refresh token | High |
| R-09 | Cookie | `HttpOnly`, `Secure`, `SameSite`, `Max-Age` attributes; behaviour over HTTP (localhost); no HTTPS stand — limitation | Medium |
| R-10 | Inactive users | Does the `is_active` model field affect login and access? | Low |
| R-11 | Rate limiting behind a proxy | The limit is keyed by client IP: behind a reverse proxy all clients may share one limit (code analysis + check in Docker) | Medium |
| R-12 | Logs | Does personal data (email) end up in logs; are records created for all key events | Medium |
| R-13 | Email case | `User@Mail.com` and `user@mail.com` — one user or two? | Medium |
| R-14 | `phone` field | No format validation | Low |
| R-15 | CORS | Only `http://localhost:3000` is allowed; preflight requests, disallowed origins / methods | Low |

---

## 4. Test environments

| Environment | URL | Purpose | Limitations |
|---|---|---|---|
| **Local (Docker)** — main | `http://localhost:8000` | All test types, database access | — |
| CI (GitHub Actions) | — | Unit tests (pytest) on SQLite | No PostgreSQL — SQLite vs PostgreSQL behaviour may differ |

**Local stand configuration:** Docker Compose (`api` + `postgres:15`), Python 3.11, variables from `.env`. For functional checklists the stand is started with the `qa/docker-compose.functional.yml` override (rate limits raised to `1000/minute`); for CL-03 — without it.

**Test data:**
- users are created via `/users/register` with unique emails (e.g. `qa<run_id>_<tag>@test.com`);
- at least 2 users (User A, User B) for access checks on other users' resources;
- a set of items (>10) for pagination checks, including deleted ones;
- data is reset by recreating the volume (`docker compose down -v`).

---

## 5. Tools

| Tool | Purpose |
|---|---|
| Run scripts (`qa/scripts/`, Python + httpx) | Executing checklists against the stand, results in `qa/runs/` |
| Postman | Manual API testing, collection `FastAPI Project - QA Testing`, environment `Fast API Local`, Collection Runner for regression |
| Swagger UI (`/docs`) | Exploring the contract, quick manual requests |
| psql / `docker exec` | Checking database state (`users`, `items`, `refresh_tokens`, `logs`) |
| Docker Compose | Deploying the stand, viewing logs (`docker compose logs api`) |
| pytest + pytest-cov | Existing unit tests, regression |
| jwt.io | Inspecting JWT contents |
| **Jira** (project `FAT`) | Main tracker: bugs, run tasks, questions to the developer, defect workflow |
| GitHub Issues | Public mirror of Jira issues in the repository (see 7.4) |

---

## 6. Criteria

### 6.1 Entry criteria
- The stand is deployed, `GET /health` returns `{"status": "ok", "database": "ok"}`;
- migrations applied without errors;
- smoke test passed ✅;
- test plan agreed;
- checklists and test data prepared.

### 6.2 Suspension criteria
- the stand is unavailable or the database does not respond;
- a blocking defect in registration / login (no token can be obtained → blocks ~80% of checks);
- requirements / API contract change during testing.

### 6.3 Resumption criteria
- the blocking defect is fixed and re-tested;
- the stand is restored, smoke test passed again.

### 6.4 Exit criteria
- 100% of planned checklist checks executed;
- ≥ 95% of checks passed;
- no open Blocker or Critical defects;
- open Major defects agreed and documented as known issues;
- all found defects filed and have a status;
- Test Summary Report prepared.

---

## 7. Defect management

### 7.1 Severity

| Level | Description | Example for this project |
|---|---|---|
| Blocker | The system / a key feature does not work, no workaround | Login always returns 500 |
| Critical | Security breach or data loss | A user can modify / delete another user's item |
| Major | A feature works incorrectly, a workaround exists | Pagination returns a wrong `total` |
| Minor | Minor deviation | Wrong response code with correct logic |
| Trivial | Cosmetic | Typo in a Swagger description |

### 7.2 Priority: Highest / High / Medium / Low / Lowest — agreed with the developer.

### 7.3 Defect lifecycle

**Bug** workflow in Jira (the Jira UI is in Russian; status names are given with English equivalents):

```
To Do ──► In Progress ──► Fixed ──► Re-test ──► Done
  │            ▲                       │
  │            └────── Reopened ───────┘   (re-test failed)
  └──► Rejected                            (not a bug / duplicate / won't fix — reason in a comment)
```

| Jira status (RU) | Status | Moved by |
|---|---|---|
| К выполнению | To Do (New / Open) | QA when filing |
| В работе | In Progress | Developer |
| Исправлено | Fixed | Developer (with the commit) |
| Повторная проверка | Re-test | QA takes it for verification |
| Готово | Done (Closed) | QA after successful verification |
| Отклонено | Rejected / Duplicate / Won't fix | Developer or QA, with justification |

### 7.4 Tracking: Jira + GitHub Issues

**Jira is the source of truth.** Every issue is filed in Jira (project `FAT`) first, and statuses are changed only there. Jira is kept in Russian.

| Jira type | What it is | Example |
|---|---|---|
| Epic | Test cycle | `FAT-1` API v1.7.0 testing — Test cycle 1 |
| Task | Preparation / checklist run / report | `FAT-3` CL-01 Auth run |
| Bug | Defect | `FAT-8` Registration: password is not validated |
| Task + `question` label | Question to the developer about ❓ checks | `FAT-20` Access token stays valid after logout — accepted limitation? |

All cycle issues are children of the cycle epic and belong to the sprint **Test cycle 1 — v1.7.0** (09.11–20.11.2026). Release `v1.7.0` exists in the project.

| Bug field | Value |
|---|---|
| Severity | Custom field: Blocker / Critical / Major / Minor / Trivial |
| Priority | Highest / High / Medium / Low / Lowest |
| Parent | Cycle epic (`FAT-1`) |
| Labels | Component: `component-auth`, `component-items`, `component-rate-limit`, `component-health-logs-cors`, `component-api-docs`; version `v1.7.0`; check ID, e.g. `CL-02_PAG-16` |
| Description | Sections per template 7.5, including **Environment** (Local (Docker), commit) |
| Web link | "mirrored in" → the GitHub mirror issue |

> The project is team-managed: components and affected versions are tracked with labels, the environment — as a description section.

**GitHub Issues — public mirror.** Jira is private, so every Jira issue is duplicated in the repository's Issues as an **English translation**:

| Jira | GitHub Issues |
|---|---|
| Key and summary | Title `[FAT-8] Registration: password is not validated…` |
| Bug description | Issue body (translated) + link to Jira |
| Type | Label `epic` / `task` / `bug` / `question` |
| Severity | Label `severity:*` |
| Label `component-*` | Label `component:*` |
| Test cycle (sprint) | Milestone `Test cycle 1 — v1.7.0` |
| Status Готово (Done) / Отклонено (Rejected) | Issue closed (completed / not planned) with a comment |
| Other statuses | Issue open; transitions duplicated as comments |

Numbers match for `FAT-1…FAT-50` ↔ `#1…#50` (issues are created in pairs, in order). GitHub issues and pull requests share one counter, so from `#51` (the first fix PR) numbers no longer match and the mirror is identified by the `[FAT-N]` prefix in its title. Fix PRs reference bugs with `Related to #N`, not `Fixes #N`: the mirror is closed only after re-test. The Jira issue has a web link to the mirror issue, the issue links back to Jira. Commits related to an issue contain its key: `docs: add bug report FAT-12`.

### 7.5 Bug report template
- **ID / Title** — Jira key; what, where, under which conditions;
- **Check** — checklist ID (e.g. `CL-02 / PAG-16`);
- **Environment** — Local (Docker), commit;
- **Preconditions**;
- **Steps to reproduce** (with the request: method, URL, headers, body — or cURL);
- **Actual result** (status + response body);
- **Expected result** (with the requirement source: README / Swagger / RFC / common practice);
- **Severity / Priority**;
- **Attachments** — Postman screenshot, logs, database state, link to the code line.

---

## 8. Deliverables

| Artifact | Stage | Status |
|---|---|---|
| Smoke report | Before start | ✅ Done |
| Test Plan (this document) | Planning | ✅ Draft |
| Module checklists: [CL-01 Auth](checklists/CL-01_Auth.md) (118), [CL-02 Items](checklists/CL-02_Items.md) (117), [CL-03 Rate limit](checklists/CL-03_RateLimit.md) (50), [CL-04 Health / Logs / CORS / Docs](checklists/CL-04_Health_Logs_CORS.md) (96) — 381 checks total | Preparation | ✅ Ready |
| Checklist run scripts and raw results (`qa/`) | Execution | ✅ All 4 checklists, cycle 1 |
| Test cases for critical scenarios | Preparation | ⏳ |
| Postman Collection (extended) + Environment | Execution | 🔄 In progress (TC-001…TC-010) |
| Bug reports (Jira + GitHub mirror) | Execution | ✅ Cycle 1: 33 bugs, 10 questions |
| Test Summary Report | Closure | ✅ [Cycle 1](reports/TSR_cycle1_v1.7.0.md) · [Cycle 2](reports/TSR_cycle2_v1.7.1.md) |
| Re-test and regression of fixes (v1.7.1) | Cycle 2 | ✅ [`retest_cycle2.py`](../qa/scripts/retest_cycle2.py), CL-01 + CL-02 re-run |

---

## 9. Schedule (estimate)

| Stage | Activities | Estimate |
|---|---|---|
| 1. Analysis and planning | Studying requirements and code, Test Plan | 0.5 day |
| 2. Preparation | Checklists, test cases, test data, Postman | 1 day |
| 3. Execution — Auth | F-01…F-05, token security | 1 day |
| 4. Execution — Items | F-06…F-10, pagination, soft delete, IDOR | 1 day |
| 5. Execution — non-functional | Rate limit, logs, CORS, health, contract | 0.5 day |
| 6. Regression and re-test | Verifying fixes | 0.5 day |
| 7. Reporting | Test Summary Report | 0.5 day |
| **Total** | | **~5 days** |

---

## 10. Project risks and mitigation

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| No formal specification — expected results are unclear | High | High | Rely on README / Swagger / common REST practice; record disputed points as questions to the developer |
| Rate limiting interferes with test execution | High | Medium | Raise limits with the `qa/docker-compose.functional.yml` override for functional testing; test rate limiting separately with default values |
| No HTTPS stand — `Secure` cookie and proxy behaviour cannot be fully verified | High | Medium | Check over HTTP, the rest by code analysis; record as a limitation in the report |
| SQLite (CI) vs PostgreSQL (stand) differences | Medium | Medium | Run manual checks on PostgreSQL |
| Token expiry (30 min / 7 days) is hard to test | High | Low | Sign a token with an expired `exp` with the stand's key inside the container; for refresh tokens — change `expires_at` in the database |
| `Secure` cookie over HTTP | Medium | Medium | Check Postman / browser behaviour on localhost; HTTPS separately |

---

## 11. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| QA Engineer | | | |
| Developer / Tech Lead | | | |
