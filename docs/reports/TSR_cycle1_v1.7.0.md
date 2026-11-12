# Test Summary Report — Test cycle 1 (API v1.7.0)

| | |
|---|---|
| Product | FastAPI Project REST API |
| Version under test | v1.7.0, commit `660708b` |
| Test cycle | 1 — Jira epic `FAT-1` ([#1](../../../../issues/1)), report task `FAT-7` ([#7](../../../../issues/7)) |
| Period | 06.11.2026 – 12.11.2026 (execution 10.11.2026) |
| Environment | Local stand, Docker Compose (API + PostgreSQL 15) |
| Prepared by | QA (Requime31) |
| Basis | [Test Plan](../TEST_PLAN.md) v1.1 |

---

## 1. Summary

All 381 planned checks were executed on build `660708b`. **300 passed, 79 failed, 2 were not applicable.** The pass rate is **79.2%**, below the 95% exit criterion.

**33 defects** were filed: **11 Major**, 20 Minor and 2 Trivial. None is Blocker or Critical, so testing was never suspended. **10 questions** about unclear requirements were sent to the developer.

Core happy paths work: registration, login, the refresh token rotation, item CRUD with ownership checks and the default rate limits. The problems are at the edges and in operations:
- input validation (passwords, pagination parameters, item titles);
- soft-deleted data leaking through `/items/all`;
- authentication edge cases (case-sensitive email, inactive users, user enumeration);
- the rate limiter, which can be bypassed in two ways;
- operational blind spots: migrations never apply, no logs reach the console, and `/health` reports `ok` while the database is down.

**Recommendation: v1.7.0 is not ready for release.** The 11 Major defects should be fixed or explicitly accepted as known issues first. Cycle 2 (section 8) starts with a first batch of fixes in the Auth module.

---

## 2. Scope

**Tested:** features F-01…F-15 from the Test Plan (section 2.1) through four checklists:

| Checklist | Module | Checks |
|---|---|---|
| [CL-01 Auth](../checklists/CL-01_Auth.md) | Registration, login, refresh, logout, logout-all, token security | 118 |
| [CL-02 Items](../checklists/CL-02_Items.md) | CRUD, pagination, soft delete, access control (IDOR), contract | 117 |
| [CL-03 Rate Limit](../checklists/CL-03_RateLimit.md) | Limits, `429` format, reset window, counter independence, bypass attempts | 50 |
| [CL-04 Health / Logs / CORS / Docs](../checklists/CL-04_Health_Logs_CORS.md) | Health check and database failure, logging, CORS, OpenAPI, setup docs | 96 |

**Not tested** (Test Plan, section 2.2, and limitations found during the cycle):
- **The author's production deployment (Railway).** It is not our service. Proxy-related behaviour was assessed by code analysis and filed as question FAT-49.
- **HTTPS-only behaviour** (the `Secure` cookie flag over TLS). The stand has no HTTPS.
- **Load and performance testing.**
- **Two checks marked ⏭.** REF-19 and ACC-14 need a deleted user with sessions or items. This is impossible because the foreign keys have no `ON DELETE CASCADE`, which is recorded as question FAT-23.

---

## 3. Approach

Each checklist is executed by a Python script in [`qa/scripts/`](../../qa/scripts/):
- every check is an HTTP request (`httpx`) to the local stand;
- database state is verified with `psql` inside the container;
- raw results are stored in [`qa/runs/`](../../qa/runs/), with tokens masked;
- the results are transferred to the checklists.

Functional checklists ran with the `qa/docker-compose.functional.yml` override (limits `1000/minute`). CL-03 ran with the default limits.

CORS check CR-20 was verified manually in a real browser (Chrome). Test design techniques: equivalence partitioning, boundary values, decision table, state transition, error guessing based on code review.

Three failures turned out to be bugs in the run scripts, not in the application. They were fixed and only the affected sections were re-run; this is noted in FAT-5. During that analysis one of them (RL-11) turned out to be a real defect (FAT-32).

---

## 4. Execution results

| Checklist | Total | ✅ Passed | ❌ Failed | ⏭ N/A | Pass rate* |
|---|---|---|---|---|---|
| CL-01 Auth | 118 | 98 | 19 | 1 | 83.8% |
| CL-02 Items | 117 | 97 | 19 | 1 | 83.6% |
| CL-03 Rate Limit | 50 | 38 | 12 | 0 | 76.0% |
| CL-04 Health / Logs / CORS / Docs | 96 | 67 | 29 | 0 | 69.8% |
| **Total** | **381** | **300** | **79** | **2** | **79.2%** |

\* Pass rate = passed / (total − not applicable).

Several failed checks can share one defect: the 79 failed checks map to 33 defects. Some ❓ checks were counted as passed and filed as questions instead, because the expected behaviour is not specified anywhere.

---

## 5. Defects

### 5.1 By severity and component

| Component | Major | Minor | Trivial | Total |
|---|---|---|---|---|
| Auth | 4 | 7 | 1 | 12 |
| Items | 2 | 5 | 1 | 8 |
| Rate Limit | 2 | 3 | — | 5 |
| Health / Logs / CORS | 3 | 4 | — | 7 |
| API Docs | — | 1 | — | 1 |
| **Total** | **11** | **20** | **2** | **33** |

Each defect is counted once under its primary component. Blocker / Critical: **0**.

### 5.2 Major defects

| Jira / GitHub | Defect | Impact |
|---|---|---|
| [FAT-8](../../../../issues/8) | Password is not validated — empty and short passwords are accepted | Accounts with an empty password |
| [FAT-9](../../../../issues/9) | Email is case-sensitive — `User@x.com` and `user@x.com` are different accounts | Duplicate accounts, failed logins |
| [FAT-10](../../../../issues/10) | Users with `is_active = false` can log in | Deactivation does not work |
| [FAT-11](../../../../issues/11) | Email enumeration through different responses and response times | Attackers can learn which emails are registered |
| [FAT-24](../../../../issues/24) | `/items/all` returns soft-deleted items | Deleted data stays visible to every user |
| [FAT-25](../../../../issues/25) | `page ≤ 0` / `limit ≤ 0` → `500` | Unhandled server errors from client input |
| [FAT-32](../../../../issues/32) | Write rate limit is counted per URL | `PUT` / `DELETE` are effectively unlimited |
| [FAT-33](../../../../issues/33) | Rejected requests (`422` / `401` / `403`) are not rate-limited | Unlimited token brute force |
| [FAT-37](../../../../issues/37) | Alembic migrations fail silently on every startup | Schema changes will not reach production |
| [FAT-38](../../../../issues/38) | No application or uvicorn logs reach the console | No diagnostics in production |
| [FAT-39](../../../../issues/39) | `/health` returns `200` / `ok` when the database is down | Monitoring cannot detect an outage |

All defects: [label:bug](../../../../issues?q=label%3Abug). All questions: [label:question](../../../../issues?q=label%3Aquestion).

### 5.3 Defect clusters

The defects are concentrated in four areas:
- **Input validation.** FAT-8, 15, 16, 25, 26, 27: request schemas declare types but no constraints.
- **Logging.** FAT-17, 19, 36, 38, 41: events are missing or incomplete, and the console output is disabled entirely.
- **Rate limiting.** FAT-32, 33, 34, 35: the limiter is applied inside handlers and keyed per URL.
- **Response contract and documentation.** FAT-13, 28, 30, 31, 34, 44: undocumented codes, internal fields in responses, missing schemas.

These areas need the most attention in regression after the fixes.

### 5.4 Questions to the developer

FAT-20…23 and FAT-45…50 are open: 10 questions about intended behaviour (token TTL after logout, public `/items/all`, `403` vs `404`, field length limits, account lockout, proxy deployment, log retention). Their answers may turn some of them into defects or close them.

---

## 6. Exit criteria (Test Plan, 6.4)

| Criterion | Result | Status |
|---|---|---|
| 100% of planned checks executed | 381 / 381 (2 not applicable, with justification) | ✅ |
| ≥ 95% of checks passed | 79.2% | ❌ |
| No open Blocker / Critical defects | 0 | ✅ |
| Open Major defects agreed and documented as known issues | 11 open, not yet agreed | ❌ |
| All found defects filed and have a status | 33 bugs + 10 questions in Jira and on GitHub | ✅ |
| Test Summary Report prepared | This document | ✅ |

**Two criteria are not met.** Cycle 1 is closed as an assessment of v1.7.0, but the build does not pass the release gate.

---

## 7. Risks and observations

1. **Operational blindness is the highest risk.** FAT-37, 38 and 39 together mean that a production failure would be invisible: the database can be down while `/health` says `ok`, and errors leave no logs. Fix these before any other non-functional work.
2. **Rate limiting gives a false sense of security.** It is configured for every endpoint, but FAT-32 and FAT-33 make it easy to bypass. FAT-49 (proxy deployment) may make one limit shared by all users.
3. **No formal requirements.** Expected results relied on the README, Swagger and common practice. The 10 open questions are a direct consequence.
4. **Developer unit tests run on SQLite** and do not catch PostgreSQL-specific behaviour (for example, row order after `UPDATE`, FAT-29).
5. **Preparation task FAT-2 is not fully finished.** The database reset script, seed data, the Postman refactor and the pytest baseline are still open. The run scripts made them non-blocking; they move to cycle 2.

---

## 8. Next steps — cycle 2

The developer has agreed to fix five Auth defects in the first batch (Major and Minor mixed). Each fix gets its own branch `fix/FAT-N-…`, a pull request and a unit test, and ships in build **v1.7.1**:

| Jira / GitHub | Defect | Severity |
|---|---|---|
| [FAT-8](../../../../issues/8) | Password is not validated | Major |
| [FAT-9](../../../../issues/9) | Email is case-sensitive | Major |
| [FAT-13](../../../../issues/13) | `403` instead of the documented `401` without `Authorization` | Minor |
| [FAT-15](../../../../issues/15) | `phone: null` is rejected | Minor |
| [FAT-19](../../../../issues/19) | Logout log record has no `user_id` | Trivial |

QA then re-tests each fix against its bug report and runs regression. The scope is CL-01 plus the parts of other checklists that the changes touch. The other 28 defects stay open as known issues of v1.7.1.

Baseline for comparison: CL-01 pass rate **83.8%**, **4** open Major defects in Auth, **33** open defects in total.
