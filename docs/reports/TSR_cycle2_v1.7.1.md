# Test Summary Report — Test cycle 2 (API v1.7.1)

| | |
|---|---|
| Product | FastAPI Project REST API |
| Version under test | v1.7.1, tag [`v1.7.1`](../../../../tree/v1.7.1), commit `5784850` |
| Previous build | v1.7.0, commit `660708b` — [cycle 1 report](TSR_cycle1_v1.7.0.md) |
| Test cycle | 2 — fix verification (re-test) and regression |
| Date | 12.11.2026 |
| Environment | Local stand, Docker Compose (API + PostgreSQL 15), `qa/docker-compose.functional.yml` |
| Prepared by | QA (Requime31) |

---

## 1. Summary

Build v1.7.1 contains fixes for five Auth defects selected after cycle 1. **Four fixes are verified and closed. One (FAT-9) is reopened**: the reported scenario works, but the fix makes accounts created before it unreachable when two of them differ only in case.

Regression found **no new failures**:
- **CL-01 Auth:** 8 checks moved from ❌ to ✅; the pass rate rose from **83.8% to 90.6%**.
- **CL-02 Items:** unchanged, 83.6%.

The developer unit tests grew from 29 to 42 and all pass, both locally and in CI.

**Recommendation: v1.7.1 is better than v1.7.0 but still not ready for release.** 10 Major defects remain open, including the reopened FAT-9. The release gate (Test Plan, 6.4) is still not met.

---

## 2. Scope of cycle 2

| Activity | Scope |
|---|---|
| Fixes | FAT-8, FAT-9, FAT-13, FAT-15, FAT-19 — PRs #51–#55 with unit tests, integrated into `master` via #56 |
| Re-test | Steps of each bug report plus checks around each fix: boundaries, neighbouring cases, legacy data. Script [`qa/scripts/retest_cycle2.py`](../../qa/scripts/retest_cycle2.py), 25 checks |
| Regression | **CL-01 Auth** in full (118 checks): all fixes are in the Auth module. **CL-02 Items** in full (117 checks): FAT-13 changed authentication on every `/items` endpoint |
| Unit tests | Full developer suite (pytest) on the stand container with the default rate limits |

**Not re-run on v1.7.1** (impact analysis):
- **CL-03 Rate Limit.** The fixes do not touch the limiter. One check, RL-36 (requests without a token are not rate-limited), now sees `401` instead of `403`. It stays failed for the same reason, FAT-33.
- **CL-04 Health / Logs / CORS / Docs.** Not affected. FAT-19 adds a field to one log record, and that is covered by the re-test.

Their cycle 1 results are carried over in section 4.

---

## 3. Re-test results

| Jira / GitHub | Defect | Severity | Checks | Result | Status |
|---|---|---|---|---|---|
| [FAT-8](../../../../issues/8) | Password is not validated | Major | RT-8-1…7 | 7 / 7 ✅ | Done |
| [FAT-9](../../../../issues/9) | Email is case-sensitive | Major | RT-9-1…6 | 5 ✅, **1 ❌** | **Reopened** |
| [FAT-13](../../../../issues/13) | `403` instead of `401` without `Authorization` | Minor | RT-13-1…7 | 7 / 7 ✅ | Done |
| [FAT-15](../../../../issues/15) | `phone: null` is rejected | Minor | RT-15-1…3 | 3 / 3 ✅ | Done |
| [FAT-19](../../../../issues/19) | Logout log has no `user_id` | Trivial | RT-19-1…2 | 2 / 2 ✅ | Done |
| **Total** | | | **25** | **24 ✅ / 1 ❌** | 4 closed, 1 reopened |

Raw results: [`qa/runs/RETEST-cycle2_2026-11-12.json`](../../qa/runs/RETEST-cycle2_2026-11-12.json).

### 3.1 FAT-9 reopened

The scenario from the bug report is fixed:
- login with the email in another case → `200`;
- registration in another case → `400 User already exists`;
- new emails are stored lower-cased.

Check **RT-9-6** goes beyond the report: *can every existing account still log in?*

Three pairs of accounts created before the fix differ only in case (ids 4/13, 38/47, 73/82). The lookup now matches `lower(email)` and returns the first row. As a result, logging in with the exact email of the second account issues a token for the **other** user:

| Account | Login with its own email → `user_id` in the token |
|---|---|
| 13 `QA1110150534_REG01@test.com` | 4 |
| 47 `QA1110150625_REG01@test.com` | 38 |
| 82 `QA1110155215_REG01@test.com` | 73 |

**In production:** a user who registered a case-duplicate address before v1.7.1 loses access to their own account. If the passwords match, they land in someone else's account; otherwise they get `401`.

**Needed to close:**
1. A data migration for case-duplicates (merge them or resolve each conflict explicitly).
2. A unique index on `lower(email)`. The index needs working migrations, so it depends on [FAT-37](../../../../issues/37).

The unit tests did not catch this: they start from an empty SQLite database, where no legacy data exists.

### 3.2 Checks around the fixes

| Fix | What else was verified |
|---|---|
| FAT-8 | Boundary: 6 characters accepted, login works; a value with spaces inside is not treated as blank |
| FAT-13 | Basic scheme and an empty `Bearer` → `401`; an invalid token now also carries `WWW-Authenticate`; the HTTPBearer scheme is still in Swagger; ownership errors stay `403` |
| FAT-15 | A non-string `phone` is still rejected with `422` |
| FAT-19 | Logout with an unknown token logs `user_id = NULL`. The `200` in that case is the separate open [FAT-14](../../../../issues/14) |

---

## 4. Regression results

| Checklist | Build | Total | ✅ | ❌ | ⏭ | Pass rate | Change |
|---|---|---|---|---|---|---|---|
| CL-01 Auth | v1.7.0 | 118 | 98 | 19 | 1 | 83.8% | |
| CL-01 Auth | **v1.7.1** | 118 | **106** | **11** | 1 | **90.6%** | +8 ✅, 0 new ❌ |
| CL-02 Items | v1.7.0 | 117 | 97 | 19 | 1 | 83.6% | |
| CL-02 Items | **v1.7.1** | 117 | 97 | 19 | 1 | 83.6% | no change |
| CL-03 Rate Limit | v1.7.0 (carried over) | 50 | 38 | 12 | 0 | 76.0% | not re-run |
| CL-04 Health / Logs / CORS / Docs | v1.7.0 (carried over) | 96 | 67 | 29 | 0 | 69.8% | not re-run |
| **All checklists** | **v1.7.1** | **381** | **308** | **71** | **2** | **81.3%** | was 79.2% |

The total for v1.7.1 combines the CL-01 and CL-02 runs on v1.7.1 with the cycle 1 results of CL-03 and CL-04.

**CL-01: checks fixed on v1.7.1**

| Check | Was (v1.7.0) | Now (v1.7.1) | Defect |
|---|---|---|---|
| REG-15, REG-16, REG-17 | `201` for `abc12`, `""`, `"      "` | `422` on `password` | FAT-8 |
| REG-13 | `201` — a second account in another case | `400 User already exists` | FAT-9 |
| LOG-11 | `404` for the email in another case | `200` | FAT-9 |
| ALL-08 | `403 Not authenticated` | `401` + `WWW-Authenticate` | FAT-13 |
| REG-27 | `422` for `phone: null` | `201` | FAT-15 |
| OUT-11 | `user_id = NULL` | `user_id` of the session owner | FAT-19 |

**SEC-10** (response codes match Swagger) is still ❌. The FAT-13 part is gone: no undocumented `403` remains. The remaining cause is the unreachable `422` documented for `/users/refresh` and `/users/logout`, which is open question [FAT-22](../../../../issues/22), not a defect.

**CL-02:** statuses are identical to cycle 1. The ownership checks (ACC-02, ACC-07 and others) still get `403 Not your item`; the FAT-13 change did not affect authorisation.

Raw results: [`CL-01_2026-11-12.json`](../../qa/runs/CL-01_2026-11-12.json), [`CL-02_2026-11-12.json`](../../qa/runs/CL-02_2026-11-12.json). The checklist documents keep the cycle 1 results.

### Unit tests

| Build | Tests | Result |
|---|---|---|
| v1.7.0 (`660708b`) | 29 | 29 passed (baseline) |
| v1.7.1 (`5784850`) | 42 | 42 passed; CI on `master` green |

One existing test, `test_access_protected_route_without_token`, was changed from `403` to `401`. It asserted the defect itself (FAT-13).

---

## 5. Defect status after cycle 2

| | v1.7.0 (after cycle 1) | v1.7.1 (after cycle 2) |
|---|---|---|
| Open defects | 33 | **29** |
| — Major | 11 | **10** (FAT-9 reopened) |
| — Minor | 20 | **18** |
| — Trivial | 2 | **1** |
| Open Major in Auth | 4 | **3** (FAT-9, FAT-10, FAT-11) |
| Closed in cycle 2 | — | 4 (FAT-8, FAT-13, FAT-15, FAT-19) |
| Reopened | — | 1 (FAT-9) |
| New defects | — | 0 |
| Open questions | 10 | 10 |

---

## 6. Exit criteria (Test Plan, 6.4)

| Criterion | v1.7.1 | Status |
|---|---|---|
| 100% of planned checks executed | Re-test and the regression scope executed; CL-03 and CL-04 carried over with justification (section 2) | ✅ |
| ≥ 95% of checks passed | 81.3% (CL-01 90.6%) | ❌ |
| No open Blocker / Critical defects | 0 | ✅ |
| Open Major defects agreed as known issues | 10 open, not agreed | ❌ |
| All found defects filed and have a status | Yes; FAT-9 reopened with details | ✅ |
| Test Summary Report prepared | This document | ✅ |

---

## 7. Process observations

1. **Stacked PRs and merge order.** #52–#55 were each based on the previous fix branch. When they were merged within seconds, each one went into its base branch instead of `master`, because GitHub retargets a stacked PR only after its base branch is deleted. Integration PR #56 brought the remaining fixes to `master`. Lesson: merge stacked PRs one at a time, deleting each branch, or base every fix on `master`.
2. **`Fixes #N` closes issues on merge.** Merging #51 auto-closed #8 before the re-test, so the issue was reopened manually. Per the defect workflow, the GitHub mirror is closed only after re-test. Fix PRs should reference bugs with `Related to #N`.
3. **Issue numbering.** GitHub issues and PRs share one counter. From #51 on, Jira keys and GitHub numbers no longer match, and the mirror is linked by the `[FAT-N]` prefix in the issue title.
4. **The QA scripts needed one change for v1.7.1.** After FAT-9, emails are stored lower-cased, while the run scripts looked users up by the exact mixed-case email. The first CL-02 run was blocked by this. The lookups were made case-insensitive and CL-02 was re-run. The application was not at fault: this is an expected consequence of the fix, recorded here as a test-maintenance cost.
5. **Automation paid off.** Re-running both checklists took a few minutes, and the per-check comparison between cycles is mechanical.

---

## 8. Next steps

1. **FAT-9:** a data migration for case-duplicates plus a unique index on `lower(email)`, after [FAT-37](../../../../issues/37) (migrations) is fixed.
2. Next fix batch by risk: operational blindness [FAT-37](../../../../issues/37), [FAT-38](../../../../issues/38), [FAT-39](../../../../issues/39), then [FAT-24](../../../../issues/24) and [FAT-25](../../../../issues/25) (Items).
3. Answers to the 10 open questions.
4. Remaining FAT-2 items: database reset script, seed data, Postman refactor.
