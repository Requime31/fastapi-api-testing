# Checklist CL-01 — Auth (Users)

| Field | Value |
|---|---|
| Module | Auth: F-01…F-05 from the [Test Plan](../TEST_PLAN.md) |
| Endpoints | `/users/register`, `/users/login`, `/users/refresh`, `/users/logout`, `/users/logout-all` |
| Product version | API v1.7.0 |
| Environment | Local (Docker), `http://localhost:8000` |
| Executed by | QA (Requime31); executed with [`qa/scripts/run_cl01_auth.py`](../../qa/scripts/run_cl01_auth.py) |
| Run date | 10.11.2026 · build `660708b` · raw results [`qa/runs/CL-01_2026-11-10.json`](../../qa/runs/CL-01_2026-11-10.json) · Jira FAT-3 ([#3](https://github.com/Requime31/fastapi-api-testing/issues/3)) |

**Legend:**
- **Priority:** H — High, M — Medium, L — Low
- **Status:** ✅ Passed · ❌ Failed · ⚠️ Blocked · ⏭ Skipped
- **❓** — the requirement is not explicitly documented; the expected result is based on common practice; on mismatch, file a question / bug
- **R-xx** — reference to a risk area in the Test Plan

**Preconditions for the whole module:**
1. The stand is running, `GET /health` → `200`, `"database": "ok"`.
2. The stand is started with `qa/docker-compose.functional.yml` (`LOGIN_RATE_LIMIT`, `REGISTER_RATE_LIMIT` = `1000/minute`). Rate limiting is tested separately in [CL-03](CL-03_RateLimit.md).
3. Two users are prepared: **User A** and **User B**.
4. Where relevant, the **database** is checked as well (`docker exec -it fastapi_postgres psql -U postgres -d fastapi_db`).

---

## 1. Registration — `POST /users/register` (F-01)

### 1.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| REG-01 | Registration with a valid email and password (6+ characters) | `201`, body `{"message": "User created"}` | ✅ | |
| REG-02 | Registration with a valid email, password and phone | `201`; `users.phone` stored in the DB | ✅ | |
| REG-03 | Registration without `phone` | `201`; `phone = NULL` in the DB | ✅ | |
| REG-04 | DB: the password is stored as a hash | `users.password` ≠ the original password, starts with `$2b$` (bcrypt) | ✅ | |
| REG-05 | DB: defaults of a new user | `is_active = true`, `id` assigned | ✅ | |
| REG-06 | The response contains no sensitive data | No `password`, hash or tokens in the body | ✅ | |
| REG-07 | Password of exactly 6 characters (boundary) | `201` | ✅ | R-01 |
| REG-08 | Email with allowed special characters: `qa+1@test.com`, `qa.name@sub.test.com` | `201` | ✅ | |
| REG-09 | Password with spaces, unicode, special characters (`p@ss w0rd!`, `пароль123`) | `201`; login with that password succeeds | ✅ | |
| REG-10 | Long password (72+ characters, bcrypt limit) | `201` or a clear `422`. ❓ Check whether login succeeds with a password that differs only in the 73rd character | ❌ | Actual: register 201; login with a changed 73rd character → 200 → **[FAT-12](https://github.com/Requime31/fastapi-api-testing/issues/12)** |
| REG-11 | A record is created in `logs` | `level = INFO`, `path = /users/register`, `user_id` = the new user's id | ✅ | R-12 |

### 1.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| REG-12 | Repeated registration with an existing email | `400`, `{"detail": "User already exists"}`; no new record in the DB | ✅ | |
| REG-13 | Existing user's email in a different case (`USER@test.com`) | ❓ `400`: email should be case-insensitive | ❌ | Actual: 201 {"message": "User created"} → **[FAT-9](https://github.com/Requime31/fastapi-api-testing/issues/9)** R-13 |
| REG-14 | Email with leading/trailing spaces (`" qa@test.com "`) | ❓ `422` or spaces are trimmed; no duplicate is created | ✅ | |
| REG-15 | Password of 5 characters (boundary) | `422`: Swagger states "minimum 6 characters" | ❌ | Actual: 201 {"message": "User created"} → **[FAT-8](https://github.com/Requime31/fastapi-api-testing/issues/8)** R-01 |
| REG-16 | Empty password `""` | `422` | ❌ | Actual: 201 {"message": "User created"} → **[FAT-8](https://github.com/Requime31/fastapi-api-testing/issues/8)** R-01 |
| REG-17 | Password of spaces only `"      "` | ❓ `422` | ❌ | Actual: 201 {"message": "User created"} → **[FAT-8](https://github.com/Requime31/fastapi-api-testing/issues/8)** R-01 |
| REG-18 | Invalid email: `"abc"`, `"abc@"`, `"@test.com"`, `"a b@test.com"`, `"a@@test.com"` | `422` naming the `email` field | ✅ | |
| REG-19 | Empty email `""` | `422` | ✅ | |
| REG-20 | `email` field missing | `422`, `"msg": "Field required"`, `loc: ["body","email"]` | ✅ | |
| REG-21 | `password` field missing | `422`, `Field required` | ✅ | |
| REG-22 | Empty body `{}` | `422` for both fields | ✅ | |
| REG-23 | Non-JSON body (plain text) / broken JSON | `422`, no `500` | ✅ | |
| REG-24 | `email = null`, `password = null` | `422` | ✅ | |
| REG-25 | Wrong types: `email: 123`, `password: 123456` (number) | `422` | ✅ | |
| REG-26 | `phone` in an invalid format (`"abc"`, `"123"`, 50 digits) | ❓ `422`: the phone format should be validated | ❌ | Actual: {'abc': 201, '123': 201, '11111111111111111111111111111111111111111111111111': 201} → **[FAT-16](https://github.com/Requime31/fastapi-api-testing/issues/16)** R-14 |
| REG-27 | Explicit `phone = null` | `201` | ❌ | Actual: 422 {"detail": [{"type": "string_type", "loc": ["body", "phone"], "msg": "Input should be a valid string", "input": null}]} → **[FAT-15](https://github.com/Requime31/fastapi-api-testing/issues/15)** |
| REG-28 | Extra fields in the body (`"is_active": false`, `"id": 999`) | Ignored: in the DB `is_active = true`, `id` auto-assigned (no mass assignment) | ✅ | |
| REG-29 | Very long email (300+ characters) | `422`; no `500` | ✅ | |
| REG-30 | SQL injection in email: `"a'--@test.com"`, `"' OR 1=1--"` | `422` or `201` as a plain string; no `500`, no changes to other data | ✅ | |
| REG-31 | Wrong method: `GET /users/register` | `405 Method Not Allowed` | ✅ | |
| REG-32 | Repeated registration → record in `logs` | `level = WARNING`, `path = /users/register` | ✅ | R-12 |

---

## 2. Login — `POST /users/login` (F-02)

### 2.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LOG-01 | Login with the correct email and password | `200`, `{"access_token": "<jwt>", "token_type": "bearer"}` | ✅ | |
| LOG-02 | The `refresh_token` cookie is set | `Set-Cookie: refresh_token=...` header present | ✅ | |
| LOG-03 | Cookie attributes | `HttpOnly`, `Secure`, `SameSite=lax`, `Max-Age=604800` (7 days) | ✅ | R-09 |
| LOG-04 | The access token is a valid JWT | jwt.io: algorithm `HS256`, payload contains `user_id` and `exp` | ✅ | |
| LOG-05 | Access token lifetime | `exp − now` ≈ 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`) | ✅ | |
| LOG-06 | The JWT payload contains no sensitive data | No password, hash, email ❓ | ✅ | |
| LOG-07 | The access token grants access to a protected endpoint | `GET /items/` with `Authorization: Bearer <token>` → `200` | ✅ | |
| LOG-08 | DB: a refresh token is created | New record in `refresh_tokens`: correct `user_id`, `revoked = false`, `expires_at` ≈ now + 7 days, `token_hash` ≠ the cookie value (SHA-256 is stored) | ✅ | |
| LOG-09 | Repeated login of the same user (2 devices) | `200`; two active records in the DB; both refresh tokens work independently | ✅ | |
| LOG-10 | Each login issues unique tokens | Access token and refresh cookie differ from the previous login | ✅ | **[FAT-21](https://github.com/Requime31/fastapi-api-testing/issues/21)** |
| LOG-11 | Login with the email in a different case | ❓ `200`: email should be case-insensitive | ❌ | Actual: 404 {"detail": "User not found"} → **[FAT-9](https://github.com/Requime31/fastapi-api-testing/issues/9)** R-13 |
| LOG-12 | A record is created in `logs` | `level = INFO`, `user_id` set | ✅ | R-12 |

### 2.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| LOG-13 | Wrong password | `401`, `{"detail": "Wrong password"}`; no cookie; no record in `refresh_tokens` | ✅ | |
| LOG-14 | Non-existent email | `404`, `{"detail": "User not found"}` (per Swagger) | ✅ | |
| LOG-15 | Compare responses of LOG-13 and LOG-14 | ❓ From a security standpoint the responses should be identical (e.g. `401 "Invalid credentials"`), otherwise emails can be enumerated. Record as a security remark | ❌ | Actual: wrong password → 401 {"detail": "Wrong password"}; no user → 404 {"detail": "User not found"} → **[FAT-11](https://github.com/Requime31/fastapi-api-testing/issues/11)** R-07 |
| LOG-16 | Password in a different case (`Password` instead of `password`) | `401`: the password is case-sensitive | ✅ | |
| LOG-17 | Password with a trailing space | `401` | ✅ | |
| LOG-18 | Empty password `""` | `401` or `422`, no `500` | ✅ | |
| LOG-19 | Invalid email format | `422` | ✅ | |
| LOG-20 | `email` / `password` field missing | `422`, `Field required` | ✅ | |
| LOG-21 | Empty body / non-JSON | `422` | ✅ | |
| LOG-22 | SQL injection in password: `"' OR '1'='1"` | `401`, no `500` | ✅ | |
| LOG-23 | Login of a user with `is_active = false` (set manually in the DB) | ❓ `401` / `403`: a deactivated user must not log in | ❌ | Actual: 200 {"access_token": "<jwt>", "token_type": "bearer"} → **[FAT-10](https://github.com/Requime31/fastapi-api-testing/issues/10)** R-10 |
| LOG-24 | Response time for a non-existent email vs a wrong password | ❓ No noticeable difference in response time (timing attack) | ❌ | Actual: no user: 5 ms, wrong password: 255 ms → **[FAT-11](https://github.com/Requime31/fastapi-api-testing/issues/11)** R-07 |
| LOG-25 | Failed login → record in `logs` | `level = WARNING`; the password does **not** get into the log | ✅ | R-12 |

---

## 3. Token refresh — `POST /users/refresh` (F-03)

> Postman stores cookies for the domain automatically. For negative checks remove or replace the cookie via **Cookies** (under the Send button) or pass it manually in a `Cookie: refresh_token=<value>` header.

### 3.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| REF-01 | Refresh with a valid cookie | `200`, `{"access_token": "...", "token_type": "bearer"}` | ✅ | |
| REF-02 | The new access token works | `GET /items/` with the new token → `200`; same `user_id` in the payload | ✅ | |
| REF-03 | Rotation: a new refresh cookie is issued | `Set-Cookie: refresh_token=<new value>` ≠ the old one; attributes as in LOG-03 | ✅ | |
| REF-04 | DB after rotation | Old record `revoked = true`; new record `revoked = false`, `expires_at` ≈ now + 7 days | ✅ | |
| REF-05 | Rotation chain (3 refreshes in a row, each with the new cookie) | `200` every time | ✅ | |
| REF-06 | Old access token after refresh | ❓ Remains valid until `exp` (stateless JWT). Record the actual behaviour | ✅ | the old access token is valid until exp (stateless JWT) — expected limitation → **[FAT-20](https://github.com/Requime31/fastapi-api-testing/issues/20)** R-08 |
| REF-07 | Cleanup of expired tokens | Set `expires_at` in the past for any record → call refresh → the record is deleted | ✅ | |

### 3.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| REF-08 | No cookie | `401`, `{"detail": "No refresh token provided"}` | ✅ | |
| REF-09 | Empty cookie `refresh_token=` | `401` | ✅ | |
| REF-10 | Random string in the cookie | `401`, `"Invalid or expired refresh token"` | ✅ | |
| REF-11 | **Reuse** of the old refresh token after rotation | `401` | ✅ | R-08 |
| REF-12 | After REF-11: does the **new** token of the same chain still work? | ❓ Reuse of a revoked token is a sign of theft. Best practice: revoke the whole chain (reuse detection). Record the actual behaviour | ❌ | Actual: new token of the chain after reuse → 200 → **[FAT-18](https://github.com/Requime31/fastapi-api-testing/issues/18)** R-08 |
| REF-13 | Refresh token revoked via logout | `401` | ✅ | |
| REF-14 | Refresh token revoked via logout-all | `401` | ✅ | |
| REF-15 | Expired refresh token (`expires_at` in the past in the DB) | `401` | ✅ | |
| REF-16 | Access token instead of the refresh token in the cookie | `401` | ✅ | |
| REF-17 | Refresh token in the `Authorization: Bearer` header instead of the cookie | `401` (`No refresh token provided`) | ✅ | |
| REF-18 | Parallel refresh requests with the same token | ❓ Only one succeeds; the others → `401` (race condition) | ✅ | |
| REF-19 | Refresh of a deleted user (delete the user from the DB manually) | `401` or `404`, no `500` | ⏭ | Actual: a user with active tokens cannot be deleted: ERROR:  update or delete on table "users" violates foreign key constraint "refresh_t…. FK refresh_tokens.user_id has no ON DELETE CASCADE — the scenario is unreachable, check not applicable → **[FAT-23](https://github.com/Requime31/fastapi-api-testing/issues/23)** |
| REF-20 | Failed refresh → record in `logs` | `level = WARNING`, the token itself does not get into the log | ✅ | R-12 |

---

## 4. Logout — `POST /users/logout` (F-04)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| OUT-01 | Logout with a valid cookie | `200`, `{"message": "Logged out"}` | ✅ | |
| OUT-02 | The cookie is removed | `Set-Cookie: refresh_token=""; Max-Age=0` (or `expires` in the past) | ✅ | |
| OUT-03 | DB: the token is revoked | That token's record has `revoked = true` | ✅ | |
| OUT-04 | Refresh after logout | `POST /users/refresh` with the old cookie → `401` | ✅ | |
| OUT-05 | Other sessions are not affected | Log in twice (2 tokens), log out with the first → refresh with the second → `200` | ✅ | |
| OUT-06 | Access token after logout | ❓ Remains valid until expiry (stateless JWT). Record as a known limitation | ✅ | the access token is valid until exp — known limitation of stateless JWT → **[FAT-20](https://github.com/Requime31/fastapi-api-testing/issues/20)** R-08 |
| OUT-07 | Logout without a cookie | `401`, `"No refresh token provided"` | ✅ | |
| OUT-08 | Logout with an invalid / random cookie | ❓ `401`. Record whether a "successful" response is returned for a non-existent token | ❌ | Actual: 200 {"message": "Logged out"} → **[FAT-14](https://github.com/Requime31/fastapi-api-testing/issues/14)** R-08 |
| OUT-09 | Repeated logout with an already revoked token | ❓ `401` or an idempotent `200`. Record the behaviour | ✅ | idempotent 200 |
| OUT-10 | Logout with an access token in `Authorization` but no cookie | `401` | ✅ | |
| OUT-11 | Record in `logs` | `level = INFO`, `path = /users/logout`; ❓ is `user_id` set | ❌ | Actual: logs: level=INFO, user_id=NULL → **[FAT-19](https://github.com/Requime31/fastapi-api-testing/issues/19)** R-12 |

---

## 5. Logout from all devices — `POST /users/logout-all` (F-05)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| ALL-01 | Logout-all with a valid access token | `200`, `{"message": "Logged out from all devices"}` | ✅ | |
| ALL-02 | All of the user's sessions are revoked | Log in 3 times (3 refresh tokens) → logout-all → refresh with each token → `401` | ✅ | |
| ALL-03 | DB | All of the user's `refresh_tokens` records have `revoked = true` | ✅ | |
| ALL-04 | **Another** user's sessions are not affected | User A calls logout-all → User B's refresh → `200` | ✅ | |
| ALL-05 | The cookie is removed | `Set-Cookie` with `Max-Age=0` | ✅ | |
| ALL-06 | New login after logout-all | `200`, the new session works | ✅ | |
| ALL-07 | Access token after logout-all | ❓ Remains valid until expiry. For "log out of all devices" this matters — record as a risk | ❌ | Actual: old access token after logout-all → 200. after "log out of all devices" access tokens stay valid for up to 30 min → **[FAT-20](https://github.com/Requime31/fastapi-api-testing/issues/20)** R-08 |
| ALL-08 | No `Authorization` header | `401` or `403` (`HTTPBearer` behaviour). Cross-check with Swagger, which documents `401` | ❌ | Actual: 403 {"detail": "Not authenticated"} → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| ALL-09 | Invalid access token (random string) | `401`, `"Invalid or expired token"` | ✅ | |
| ALL-10 | Expired access token | `401` | ✅ | a token with exp in the past, signed with the stand's key |
| ALL-11 | JWT signed with a different key | `401` | ✅ | |
| ALL-12 | JWT with a modified `user_id` in the payload without re-signing | `401` | ✅ | |
| ALL-13 | Wrong scheme: `Authorization: Token <jwt>` / `Basic ...` / no `Bearer` | `401` / `403` | ✅ | |
| ALL-14 | Refresh cookie only, no access token | `401` / `403` | ✅ | |
| ALL-15 | User without active sessions | `200`, no errors | ✅ | |
| ALL-16 | Record in `logs` | `level = INFO`, `user_id` set | ✅ | R-12 |

---

## 6. Cross-cutting security and contract checks (Auth)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| SEC-01 | Protected endpoint without a token (`GET /items/`) | `401` / `403`. Cross-check with the documentation | ✅ | 403 instead of 401 — codes for protected endpoints are not documented in Swagger R-06 |
| SEC-02 | JWT with `"alg": "none"` | `401` | ✅ | |
| SEC-03 | Valid JWT of a deleted user (delete from the DB) | `401`, `"User not found"` | ✅ | |
| SEC-04 | Valid JWT of a deactivated user (`is_active = false`) | ❓ `401` / `403` | ❌ | Actual: 200 [] → **[FAT-10](https://github.com/Requime31/fastapi-api-testing/issues/10)** R-10 |
| SEC-05 | JWT with `exp` far in the future, signed with a foreign key | `401` | ✅ | |
| SEC-06 | Errors do not expose internals | No stack trace, SQL or file paths in responses | ✅ | |
| SEC-07 | Logs contain no passwords or tokens | Check the `logs` table and `docker compose logs api` after all module checks | ✅ | R-12 |
| SEC-08 | Email (PII) in logs | ❓ Emails are written to `logs.message` in plain text. Record as a remark | ❌ | Actual: logs records with emails of this run: 82 → **[FAT-17](https://github.com/Requime31/fastapi-api-testing/issues/17)** R-12 |
| SEC-09 | Response `Content-Type` | `application/json` for all endpoints | ✅ | |
| SEC-10 | Response codes match Swagger (`/openapi.json`) | Every documented code is reproducible; undocumented codes (`403`, `422`) are recorded | ❌ | Actual: not reproduced: ['/users/refresh:422', '/users/logout:422']; undocumented: ['/users/logout-all:403'] → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| SEC-11 | Cookie over HTTP (localhost) | ❓ `Secure` cookie over HTTP: is it stored and sent on refresh (Postman / browser)? HTTPS behaviour is not checked (no HTTPS stand) — mark as a limitation | ✅ | a client with strict Secure handling does not send the cookie over HTTP; Chrome treats localhost as a secure context and sends it. HTTPS not checked (no stand) R-09 |

---

## 7. E2E scenarios

| ID | Scenario | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| E2E-01 | Register → Login → `GET /items/` → Refresh → `GET /items/` with the new token → Logout → Refresh | All steps succeed, the last refresh → `401` | ✅ | |
| E2E-02 | Login (device 1) → Login (device 2) → Logout device 1 → Refresh device 2 → Logout-all → Refresh device 2 | `200` → … → the last refresh `401` | ✅ | |
| E2E-03 | Register → repeated Register → Login with a wrong password → Login with the correct one | `201` → `400` → `401` → `200`; 4 records with correct levels in `logs` | ✅ | |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Register | 32 | 25 | 7 | 0 | 0 |
| 2. Login | 25 | 21 | 4 | 0 | 0 |
| 3. Refresh | 20 | 18 | 1 | 0 | 1 |
| 4. Logout | 11 | 9 | 2 | 0 | 0 |
| 5. Logout-all | 16 | 14 | 2 | 0 | 0 |
| 6. Security / Contract | 11 | 8 | 3 | 0 | 0 |
| 7. E2E | 3 | 3 | 0 | 0 | 0 |
| **Total** | **118** | **98** | **19** | **0** | **1** |

Pass rate: **83.8%** (excluding ⏭). The module does not meet the exit criterion "≥ 95% passed".

**Defects found:** filed in Jira (project FAT, parent FAT-1) and mirrored to GitHub Issues — key FAT-N matches issue #N.

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| [FAT-8](https://github.com/Requime31/fastapi-api-testing/issues/8) | REG-15, REG-16, REG-17 | Registration: password is not validated — empty, whitespace-only and shorter than 6 characters are accepted | Major |
| [FAT-9](https://github.com/Requime31/fastapi-api-testing/issues/9) | REG-13, LOG-11 | Email is case-sensitive: `User@x.com` and `user@x.com` are different accounts, login in another case → 404 | Major |
| [FAT-10](https://github.com/Requime31/fastapi-api-testing/issues/10) | LOG-23, SEC-04 | A user with `is_active = false` can log in and their tokens keep working | Major |
| [FAT-11](https://github.com/Requime31/fastapi-api-testing/issues/11) | LOG-15, LOG-24 | Login: email enumeration — different responses (401 / 404) and response times (~4 ms vs ~250 ms) | Major |
| [FAT-12](https://github.com/Requime31/fastapi-api-testing/issues/12) | REG-10 | Password is silently truncated to 72 bytes (bcrypt) | Minor |
| [FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13) | ALL-08, SEC-10 | Request without `Authorization` returns 403 instead of the documented 401 | Minor |
| [FAT-14](https://github.com/Requime31/fastapi-api-testing/issues/14) | OUT-08 | Logout with a non-existent refresh token returns 200 "Logged out" | Minor |
| [FAT-15](https://github.com/Requime31/fastapi-api-testing/issues/15) | REG-27 | Registration: `phone: null` is rejected with 422 although the field is optional | Minor |
| [FAT-16](https://github.com/Requime31/fastapi-api-testing/issues/16) | REG-26 | Registration: `phone` format is not validated | Minor |
| [FAT-17](https://github.com/Requime31/fastapi-api-testing/issues/17) | SEC-08 | User emails (PII) are written to `logs.message` in plain text | Minor |
| [FAT-18](https://github.com/Requime31/fastapi-api-testing/issues/18) | REF-12 | No reuse detection: the token chain keeps working after a revoked refresh token is reused | Minor |
| [FAT-19](https://github.com/Requime31/fastapi-api-testing/issues/19) | OUT-11 | Logout log record has no `user_id` | Trivial |

**Questions to the developer (❓ checks):** filed as tasks with the `question` label.

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| [FAT-20](https://github.com/Requime31/fastapi-api-testing/issues/20) | ALL-07, OUT-06, REF-06 | The access token stays valid for up to 30 min after logout / logout-all (stateless JWT). Is this an accepted limitation or is a denylist / shorter TTL needed? | |
| [FAT-21](https://github.com/Requime31/fastapi-api-testing/issues/21) | LOG-10 | The JWT payload has no `iat` / `jti`: two logins within one second produce an identical access token (reproduced in 1 of 2 runs). Is token uniqueness required? | |
| [FAT-22](https://github.com/Requime31/fastapi-api-testing/issues/22) | SEC-10 | Swagger documents an unreachable 422 for `/users/refresh` and `/users/logout` (auto-generated by FastAPI). Remove it from the spec? | |
| [FAT-23](https://github.com/Requime31/fastapi-api-testing/issues/23) | REF-19 | `refresh_tokens.user_id` and `items.owner_id` have no `ON DELETE CASCADE` — a user with sessions cannot be deleted. How is account deletion planned? | |
