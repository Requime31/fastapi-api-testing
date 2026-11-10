# Checklist CL-03 — Rate Limiting

| Field | Value |
|---|---|
| Module | Rate limiting: F-12 from the [Test Plan](../TEST_PLAN.md) |
| Implementation | `slowapi 0.1.9`: `SlowAPIMiddleware` + `@limiter.limit` decorator on endpoints, key — client IP (`get_remote_address`) |
| Product version | API v1.7.0 |
| Environment | Local (Docker), `http://localhost:8000` |
| Executed by | |
| Run date | |

**Legend:**
- **Priority:** H — High, M — Medium, L — Low
- **Status:** ✅ Passed · ❌ Failed · ⚠️ Blocked · ⏭ Skipped
- **❓** — the requirement is not explicitly documented; the expected result is based on common practice; on mismatch, file a question / bug
- **R-xx** — reference to a risk area in the Test Plan

---

## 0. Preparation

### 0.1 Default limits (from `README.md` and `app/config.py`)

| Endpoint | Variable | Limit |
|---|---|---|
| `POST /users/register` | `REGISTER_RATE_LIMIT` | 3 / minute |
| `POST /users/login` | `LOGIN_RATE_LIMIT` | 5 / minute |
| `POST /users/refresh`, `/logout`, `/logout-all` | `DEFAULT_RATE_LIMIT` | 100 / minute |
| `GET /health` | `DEFAULT_RATE_LIMIT` | 100 / minute |
| `GET /items/`, `GET /items/all` | `ITEMS_READ_RATE_LIMIT` | 60 / minute |
| `POST /items/`, `PUT /items/{id}`, `DELETE /items/{id}` | `ITEMS_WRITE_RATE_LIMIT` | 30 / minute |
| `/docs`, `/openapi.json` (no decorator) | `default_limits` | ❓ 100 / minute |

### 0.2 Preconditions
1. The stand is started **without** the `qa/docker-compose.functional.yml` override, i.e. default limits apply. Exception: section 6, where limits are changed on purpose.
2. Counters are reset before each check in one of these ways:
   - wait 60 seconds for the window to end;
   - restart the API: `docker compose restart api`. Counters are kept in process memory — this is also checked in RL-41.
3. A logged-in user (`{{token}}`) and a refresh cookie are prepared.
4. For login/register checks, get the token in advance so that the login in the preparation does not use up the limit.

### 0.3 Tools for request series

**Postman Collection Runner** — the request in a separate folder, `Iterations = N + 1`, `Delay = 0`. Log the status in Tests: `console.log(pm.info.iteration, pm.response.code)`.

**curl loop** (easier to count):

```bash
for i in $(seq 1 6); do
  printf "%s: " "$i"
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/users/login \
    -H "Content-Type: application/json" \
    -d '{"email":"rl@test.com","password":"wrong"}'
done
```

Headers and body of the last response: `curl -i ...`.

---

## 1. Limits per endpoint

> For each row: send N requests in a row (N = limit) → none should get `429`; request N+1 → `429`.

| ID | Endpoint | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|---|
| RL-01 | `POST /users/login` | 5 requests, then the 6th | 1–5: not `429` (`200` / `401` / `404`); 6th: `429` | H | | |
| RL-02 | `POST /users/register` | 3 registrations with unique emails, then the 4th | 1–3: `201`; 4th: `429`; the 4th user is **not** created in the DB | H | | |
| RL-03 | `POST /users/refresh` | 100 requests, then the 101st | 101st: `429` | M | | |
| RL-04 | `POST /users/logout` | 100 requests without a cookie (`401`), then the 101st | 101st: `429` | L | | |
| RL-05 | `POST /users/logout-all` | 100 requests with a valid token, then the 101st | 101st: `429` | L | | |
| RL-06 | `GET /health` | 100 requests, then the 101st | 101st: `429` | M | | |
| RL-07 | `GET /items/` | 60 requests, then the 61st | 61st: `429` | H | | |
| RL-08 | `GET /items/all` | 60 requests, then the 61st | 61st: `429` | M | | |
| RL-09 | `POST /items/` | 30 requests, then the 31st | 1–30: `201`; 31st: `429`; exactly 30 new items in the DB | H | | |
| RL-10 | `PUT /items/{id}` | 30 requests, then the 31st | 31st: `429`; item data not changed by the 31st request | M | | |
| RL-11 | `DELETE /items/{id}` | 30 requests (different ids), then the 31st | 31st: `429`; the 31st item is **not** deleted | M | | |
| RL-12 | `GET /docs`, `GET /openapi.json` | 100 requests, then the 101st | ❓ Record whether `default_limits` applies to endpoints without a decorator | L | | |

---

## 2. `429` response format

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| RL-13 | Status code | `429 Too Many Requests` | H | | |
| RL-14 | Response body | JSON with an `error` field, e.g. `{"error": "Rate limit exceeded: 5 per 1 minute"}` | H | | |
| RL-15 | Consistent error format | ❓ Other API errors use `{"detail": ...}`, while `429` uses `{"error": ...}`. Record the mismatch as a contract remark | L | | R-06 |
| RL-16 | `Content-Type` | `application/json` | L | | |
| RL-17 | `Retry-After` header | ❓ Present and contains the number of seconds until reset (RFC 6585 recommends it for `429`) | M | | |
| RL-18 | `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers | ❓ Present in successful responses and in `429`. Record whether they actually exist | L | | |
| RL-19 | `429` is documented in Swagger | ❓ `/openapi.json` describes a `429` response for rate-limited endpoints | L | | R-06 |
| RL-20 | `429` response does not expose internals | No stack trace or internal data | M | | |

---

## 3. Window and counter reset

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| RL-21 | Reset after the window | Exhaust the login limit → wait 60 s → the request goes through (not `429`) | H | | |
| RL-22 | Request before the window ends | Exhaust the limit → wait ~30 s → still `429` | M | | |
| RL-23 | Rejected requests do not extend the block | Exhaust the limit → send a request every 10 s for a minute → 60 s after the **first** request access is restored | M | | |
| RL-24 | Window boundary (fixed window) | 5 logins at the end of a minute (seconds 55–59) + 5 at the start of the next → ❓ all 10 pass: fixed window allows a 2×N burst. Record the strategy | L | | |
| RL-25 | Steady flow within the limit | 5 logins with a 12 s interval for several minutes → no `429` | L | | |

---

## 4. Counter independence

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| RL-26 | Different endpoints do not share a counter | Exhaust login (5) → `POST /users/register` goes through | H | | |
| RL-27 | Items read and write limits are independent | Exhaust `POST /items/` (30) → `GET /items/` returns `200` | H | | |
| RL-28 | `GET /items/` and `GET /items/all` | ❓ Separate counters (per-route limit): exhaust `/items/` → `/items/all` → `200`. Record | M | | |
| RL-29 | Items `POST`, `PUT` and `DELETE` | ❓ Separate counters or a shared one. Record | L | | |
| RL-30 | Different users from the same IP | User A exhausts `GET /items/` → User B from the same IP gets `429` (the key is the IP, not the user). ❓ Record as a property: users behind a shared NAT / office block each other | M | | R-11 |
| RL-31 | Different emails on login from the same IP | 5 logins with different emails → 6th with a new email → `429`. The limit protects against brute force per IP, not per account | M | | |
| RL-32 | Password brute force on one account from different IPs | ❓ There is no per-account limit — N addresses allow 5×N attempts per minute. Record as a security remark (no account lockout) | L | | R-11 |

---

## 5. Which requests are counted

> Checks in this section find out whether the limit is consumed by requests rejected **before** the endpoint runs (body validation, authorization). For each: send 10 "bad" requests, then 1 valid one.

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| RL-33 | Failed logins (`401` wrong password) are counted | 5 × `401` → 6th `429` | H | | |
| RL-34 | Logins with an invalid body (`422`) are counted | ❓ 10 × `422` (e.g. `email: "abc"`) → expected: `429` after the 5th. If all 10 return `422`, the limit can be bypassed with invalid requests | M | | |
| RL-35 | Duplicate registration (`400`) is counted | 3 × `400` → 4th `429` | M | | |
| RL-36 | Items requests without a token (`401` / `403`) | ❓ Record whether unauthenticated requests are counted. Send 61 `GET /items/` requests without a token | M | | |
| RL-37 | Requests with an invalid token | ❓ Same as RL-36 with `Authorization: Bearer invalid` | L | | |
| RL-38 | Requests rejected with `429` have no side effects | After RL-09 and RL-02 there are no extra records in the DB; no extra tokens in `refresh_tokens` after RL-01 with the correct password | H | | |
| RL-39 | `429` written to logs | ❓ Record whether limit violations are logged (in `logs` and in `docker compose logs api`). Useful for attack analysis | L | | R-12 |

---

## 6. Configuration, storage, bypass

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| RL-40 | The limit is read from `.env` | `LOGIN_RATE_LIMIT=2/minute` → restart → 3rd login `429`. Restore the value afterwards | M | | |
| RL-41 | Restart resets counters | Exhaust login → `docker compose restart api` → login goes through. Confirms in-memory storage: with several workers or instances counters are not shared. Record as a limitation | L | | |
| RL-42 | Invalid limit value in `.env` (`LOGIN_RATE_LIMIT=abc`) | ❓ The app does not start with a clear error or logs it; it does not silently run without a limit | L | | |
| RL-43 | Spoofing `X-Forwarded-For` does not bypass the limit | Exhaust login → send with `X-Forwarded-For: 1.2.3.4`, `5.6.7.8`, … → `429` | H | | |
| RL-44 | Spoofing `X-Real-IP` does not bypass the limit | Same as RL-43 | M | | |
| RL-45 | Path variants do not get a separate counter | Exhaust `/items/` → `/items` (no slash), `/items/?x=1`, `/ITEMS/` → `429` or `404`/`307`, but not `200` | M | | |
| RL-46 | IP detection in Docker | Compare `logs.ip` / slowapi logs: ❓ do all requests come from the Docker gateway IP? If so, the limit is effectively shared by all clients of the stand | M | | R-11 |
| RL-47 | Behaviour behind a reverse proxy (code analysis) | ❓ The limit key is `request.client.host`; `X-Forwarded-For` is ignored. Behind a proxy all users get the proxy IP and a shared limit: one client can block login for everyone. Discuss with the developer | M | | R-11 |

---

## 7. Scenarios

| ID | Scenario | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| E2E-01 | Brute force: 20 login attempts with a wrong password in a row, then the correct password | 1–5: `401`; 6–20: `429`; correct password: `429` until the window ends, then `200` | H | | |
| E2E-02 | Normal user activity: login → 10 × `GET /items/` → 5 × `POST /items/` → refresh → logout | No `429` | H | | |
| E2E-03 | Create spam: 40 × `POST /items/` | 30 × `201`, 10 × `429`; exactly 30 items in the DB | M | | |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Limits per endpoint | 12 | | | | |
| 2. 429 format | 8 | | | | |
| 3. Window and reset | 5 | | | | |
| 4. Counter independence | 7 | | | | |
| 5. Which requests are counted | 7 | | | | |
| 6. Configuration and bypass | 8 | | | | |
| 7. Scenarios | 3 | | | | |
| **Total** | **50** | | | | |

**Defects found:**

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| | | | |

**Questions to the developer (❓ checks):**

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| | | | |
