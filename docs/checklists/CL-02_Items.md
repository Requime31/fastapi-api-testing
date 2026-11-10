# Checklist CL-02 — Items

| Field | Value |
|---|---|
| Module | Items: F-06…F-10 from the [Test Plan](../TEST_PLAN.md) |
| Endpoints | `POST /items/`, `GET /items/`, `GET /items/all`, `PUT /items/{item_id}`, `DELETE /items/{item_id}` |
| Product version | API v1.7.0 |
| Environment | Local (Docker), `http://localhost:8000` |
| Executed by | QA (Requime31); executed with [`qa/scripts/run_cl02_items.py`](../../qa/scripts/run_cl02_items.py) |
| Run date | 10.11.2026 · build `660708b` · raw results [`qa/runs/CL-02_2026-11-10.json`](../../qa/runs/CL-02_2026-11-10.json) · Jira FAT-4 ([#4](https://github.com/Requime31/fastapi-api-testing/issues/4)) |

**Legend:**
- **Priority:** H — High, M — Medium, L — Low
- **Status:** ✅ Passed · ❌ Failed · ⚠️ Blocked · ⏭ Skipped
- **❓** — the requirement is not explicitly documented; the expected result is based on common practice; on mismatch, file a question / bug
- **R-xx** — reference to a risk area in the Test Plan

**Preconditions for the whole module:**
1. The stand is running, `GET /health` → `200`.
2. The stand is started with `qa/docker-compose.functional.yml` (`ITEMS_READ_RATE_LIMIT` and `ITEMS_WRITE_RATE_LIMIT` = `1000/minute`). Rate limiting is tested separately in [CL-03](CL-03_RateLimit.md).
3. Two logged-in users exist: **User A** (`{{token_a}}`) and **User B** (`{{token_b}}`). All requests use `Authorization: Bearer <token>` unless stated otherwise.
4. For pagination checks: the items table is cleared (`docker compose down -v` or `DELETE FROM items;`), then **25 items** are created (15 by User A, 10 by User B).
5. Database state is checked with queries like `SELECT * FROM items WHERE id = <id>;`.

---

## 1. Create item — `POST /items/` (F-06)

### 1.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CRT-01 | Create with valid `title` and `description` | `201`; body contains `id`, `title`, `description` matching the request | ✅ | |
| CRT-02 | DB: record created correctly | `owner_id` = User A id, `is_deleted = false`, `created_at` and `updated_at` set (UTC, ≈ now) | ✅ | |
| CRT-03 | `id` is assigned automatically and is unique | Two consecutive creates → different `id`, the second is greater | ✅ | |
| CRT-04 | Response fields | ❓ The response matches the `ItemResponse` schema (`id`, `title`, `description`). Record if internal fields are returned (`owner_id`, `is_deleted`, `created_at`, …) | ❌ | Actual: response fields: ['created_at', 'description', 'id', 'is_deleted', 'owner_id', 'title', 'updated_at'] → **D-17** R-05 |
| CRT-05 | The created item appears in `GET /items/` | The item is in User A's list | ✅ | |
| CRT-06 | Two items with the same `title` | `201` both times (uniqueness not required) | ✅ | |
| CRT-07 | Unicode and emoji: `"Заметка 📝"`, `"日本語"` | `201`; strings stored without distortion in the response and in the DB | ✅ | |
| CRT-08 | Special characters: `"<>&\"'/\\%"` | `201`; stored as is, without escaping or truncation | ✅ | |
| CRT-09 | 1-character string in both fields | `201` | ✅ | |
| CRT-10 | Long strings (1,000 and 10,000 characters) | ❓ `201` or `422` with a clear limit; no `500` | ✅ | no length limit: 10,000-character strings are accepted → **Q-07** R-02 |
| CRT-11 | Record in `logs` | `level = INFO`, `message = item_created`, `user_id`, `path = /items/`, `method = POST`, `status_code = 201` | ✅ | R-12 |

### 1.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CRT-12 | Empty `title: ""` | ❓ `422`: an item without a title makes no sense | ❌ | Actual: 201 {"id": 14, "updated_at": "2026-11-10T15:11:48.875627", "is_deleted": false, "owner_id": 107, "description": "desc", "title": … → **D-16** R-02 |
| CRT-13 | Empty `description: ""` | ❓ `422` or `201`. Record the behaviour | ✅ | an empty description is accepted R-02 |
| CRT-14 | `title` of spaces `"   "` | ❓ `422` | ❌ | Actual: 201 {"id": 16, "updated_at": "2026-11-10T15:11:48.886734", "is_deleted": false, "owner_id": 107, "description": "desc", "title": … → **D-16** R-02 |
| CRT-15 | `title` missing | `422`, `Field required`, `loc: ["body","title"]` | ✅ | |
| CRT-16 | `description` missing | `422`, `Field required` | ✅ | |
| CRT-17 | Empty body `{}` | `422` for both fields | ✅ | |
| CRT-18 | `title: null` | `422` | ✅ | |
| CRT-19 | Wrong types: `title: 123`, `title: true`, `title: ["a"]`, `title: {}` | `422` | ✅ | |
| CRT-20 | Invalid JSON / `Content-Type: text/plain` | `422`, no `500` | ✅ | |
| CRT-21 | Extra fields: `"owner_id": <User B id>`, `"is_deleted": true`, `"id": 9999` | Ignored: in the DB `owner_id` = User A, `is_deleted = false`, `id` auto-assigned (no mass assignment) | ✅ | |
| CRT-22 | HTML/JS in `title`: `"<script>alert(1)</script>"` | `201`, stored as text. ❓ Record as a stored XSS risk for a future frontend | ✅ | HTML/JS is stored and returned as is — stored XSS risk for a future frontend (output encoding is the frontend's job) R-02 |
| CRT-23 | SQL injection in `title`: `"'; DROP TABLE items;--"` | `201`, stored as a string; `items` table intact; no `500` | ✅ | |
| CRT-24 | No `Authorization` header | `401` / `403`; item not created | ✅ | 403 instead of 401 — same root cause as FAT-13 → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| CRT-25 | Invalid / expired token | `401`, `"Invalid or expired token"`; item not created | ✅ | |
| CRT-26 | Refresh token instead of access token in the header | `401` | ✅ | |

---

## 2. My items — `GET /items/` (F-07)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| MY-01 | User without items | `200`, `[]` | ✅ | |
| MY-02 | User with several items | `200`, array with all of the user's items | ✅ | |
| MY-03 | Data isolation | User A sees only their own items, User B's items are absent (and vice versa) | ✅ | |
| MY-04 | Deleted items are not returned | Delete an item → it is not in `GET /items/` | ✅ | R-04 |
| MY-05 | An updated item is returned with new data | After `PUT` the list contains the new `title` / `description` | ✅ | |
| MY-06 | Structure of each element | ❓ Fields as in `ItemResponse`; record extra fields | ❌ | Actual: element fields: ['created_at', 'description', 'id', 'is_deleted', 'owner_id', 'title', 'updated_at'] → **D-17** R-05 |
| MY-07 | Element order | ❓ Deterministic (e.g. by `id` or `created_at`). Record the actual order | ❌ | Actual: order after an update: [22, 21] → **D-18** |
| MY-08 | Large number of items (100+) | ❓ All returned without pagination, acceptable response time. Record as a growth risk | ✅ | the endpoint has no pagination — the response grows with the number of items |
| MY-09 | No token | `401` / `403` | ✅ | 403 instead of 401 — see FAT-13 → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| MY-10 | Invalid token | `401` | ✅ | |
| MY-11 | Query parameters are ignored (`?owner_id=<User B id>`) | Only the current user's items are returned | ✅ | |
| MY-12 | Path without trailing slash `/items` | `200` or `307` redirect to `/items/`. ❓ Record whether `Authorization` is kept after the redirect | ✅ | redirect to http://localhost:8000/items/; following with the same Authorization → 200 |

---

## 3. All items with pagination — `GET /items/all` (F-08)

> Precondition: the DB contains exactly 25 items (item 4 of the module preconditions), 0 of them deleted unless stated otherwise.

### 3.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-01 | No parameters | `200`; `page = 1`, `limit = 10`, `total = 25`, `pages = 3`, 10 elements in `data` | ✅ | |
| PAG-02 | Response structure | Fields `page`, `limit`, `total`, `pages`, `data`; types: numbers and an array | ✅ | |
| PAG-03 | `page=2&limit=10` | 10 elements, no overlap with page 1 | ✅ | |
| PAG-04 | `page=3&limit=10` (last, partial) | 5 elements | ✅ | |
| PAG-05 | Walk through all pages | The union of `data` from all pages = 25 unique items, no duplicates or gaps | ✅ | |
| PAG-06 | `page=4&limit=10` (out of range) | `200`, `data = []`, `total = 25`. ❓ Or `404` — record | ✅ | R-03 |
| PAG-07 | `limit=1` (boundary) | 1 element, `pages = 25` | ✅ | R-03 |
| PAG-08 | `limit=25` (= total) | 25 elements, `pages = 1` | ✅ | |
| PAG-09 | `limit=100` (> total) | 25 elements, `pages = 1` | ✅ | |
| PAG-10 | Items of all users are returned | `data` contains items of both User A and User B | ✅ | |
| PAG-11 | Stable order | Two identical requests → the same order. ❓ Without `ORDER BY`, PostgreSQL does not guarantee the order — record | ✅ | the query has no ORDER BY — stable here, but PostgreSQL does not guarantee the order (e.g. after updates) |
| PAG-12 | Empty DB | `200`, `total = 0`, `pages = 0`, `data = []` | ✅ | |

### 3.2 Soft delete in pagination

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-13 | Delete 5 items → `GET /items/all?limit=100` | Deleted items are **absent** from `data` | ❌ | Actual: deleted items still in data: 5 of 5 → **D-13** R-04 |
| PAG-14 | `total` after deleting 5 items | `total = 20`, `pages` recalculated | ❌ | Actual: total after deleting 5 = 25, pages = 1 → **D-13** R-04 |
| PAG-15 | Consistency of `GET /items/` and `GET /items/all` | Number of User A's items in `/items/all` = length of User A's `/items/` response | ❌ | Actual: User A: GET /items/ → 10, User A items in /items/all → 15 → **D-13** R-04 |

### 3.3 Negative and boundary checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-16 | `page=0` | `422` (pages start at 1); no `500` | ❌ | Actual: page=0 → 500 Internal Server Error → **D-14** R-03 |
| PAG-17 | `page=-1` | `422`; no `500` | ❌ | Actual: page=-1 → 500 Internal Server Error → **D-14** R-03 |
| PAG-18 | `limit=0` | `422`; no `500` | ❌ | Actual: limit=0 → 500 Internal Server Error → **D-14** R-03 |
| PAG-19 | `limit=-5` | `422`; no `500` | ❌ | Actual: limit=-5 → 500 Internal Server Error → **D-14** R-03 |
| PAG-20 | `limit=100000` | ❓ Capped at a maximum (e.g. 100) or `422`. Record whether the whole table can be dumped in one request | ❌ | Actual: limit=100000 → 200, limit in response=100000, returned 25 (all rows) → **D-15** R-03 |
| PAG-21 | Non-numeric values: `page=abc`, `limit=1.5`, `page=` | `422` naming the parameter | ✅ | |
| PAG-22 | Very large `page=999999999999` | `200` with empty `data` or `422`; no `500` | ✅ | R-03 |
| PAG-23 | No token | `401` / `403` | ✅ | 403 instead of 401 — see FAT-13 → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| PAG-24 | Visibility of other users' items | ❓ Any authenticated user sees all users' items. Clarify whether this is intended (README: "Get all items"). Check whether `owner_id` / email are exposed | ✅ | any user sees all users' items with ['owner_id'] — confirm that a public list of all items is intended → **Q-05** R-05 |

---

## 4. Update item — `PUT /items/{item_id}` (F-09)

### 4.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| UPD-01 | The owner updates their item | `200`; the response contains the new `title` and `description`, same `id` | ✅ | |
| UPD-02 | DB after the update | Data changed, `owner_id` and `created_at` unchanged, `updated_at` > `created_at` | ✅ | |
| UPD-03 | Update with the same values | `200`, data unchanged | ✅ | |
| UPD-04 | Repeated updates | `200` each time, the DB holds the last value | ✅ | |
| UPD-05 | Record in `logs` | `level = INFO`, `message = item_updated`, `status_code = 200` | ✅ | R-12 |

### 4.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| UPD-06 | Partial update: `title` only | `422` (PUT requires the full object). ❓ A partial update would be `PATCH` | ✅ | |
| UPD-07 | Empty body `{}` | `422` | ✅ | |
| UPD-08 | Invalid values (empty strings, `null`, wrong types) | Same rules as CRT-12…CRT-19 | ❌ | Actual: title → code: {"''": 200, 'None': 422, '123': 422} → **D-16** R-02 |
| UPD-09 | Attempt to change the owner: `"owner_id": <User B id>` in the body | Ignored: `owner_id` in the DB does not change | ✅ | |
| UPD-10 | Attempt to restore a deleted item: `"is_deleted": false` in the body | Ignored | ✅ | |
| UPD-11 | Non-existent `item_id` (e.g. 999999) | `404`, `"Item not found"` | ✅ | |
| UPD-12 | Deleted (soft delete) item | `404`; DB data unchanged | ✅ | R-04 |
| UPD-13 | Non-numeric `item_id` (`/items/abc`) | `422` | ✅ | |
| UPD-14 | `item_id = 0`, `-1` | `404` or `422`; no `500` | ✅ | |
| UPD-15 | `item_id` beyond int range (`99999999999999999999`) | `422` or `404`; no `500` | ✅ | |
| UPD-16 | No token | `401` / `403`; data unchanged | ✅ | 403 instead of 401 — see FAT-13 → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| UPD-17 | Invalid token | `401`; data unchanged | ✅ | |

---

## 5. Delete item — `DELETE /items/{item_id}` (F-10)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DEL-01 | The owner deletes their item | `204 No Content` | ✅ | |
| DEL-02 | Body of the `204` response | Empty (per HTTP, `204` has no body). Check the Body tab and the `Content-Length` header | ✅ | R-06 |
| DEL-03 | Soft delete in the DB | The record **remains** in the table, `is_deleted = true` | ✅ | |
| DEL-04 | The deleted item disappears from `GET /items/` | Not in the list | ✅ | R-04 |
| DEL-05 | The deleted item disappears from `GET /items/all` | Not in `data`, `total` decreased | ❌ | Actual: in /items/all: True; total 127 → 127 → **D-13** R-04 |
| DEL-06 | Deleting the same item again | `404`, `"Item not found"` | ✅ | |
| DEL-07 | The user's other items are not affected | Delete 1 of 3 → 2 remain in the list | ✅ | |
| DEL-08 | Non-existent `item_id` | `404` | ✅ | |
| DEL-09 | Non-numeric `item_id` | `422` | ✅ | |
| DEL-10 | No token | `401` / `403`; item not deleted | ✅ | 403 instead of 401 — see FAT-13 → **[FAT-13](https://github.com/Requime31/fastapi-api-testing/issues/13)** R-06 |
| DEL-11 | Invalid token | `401`; item not deleted | ✅ | |
| DEL-12 | Record in `logs` | `level = INFO`, `message = item_deleted`, `status_code = 204` | ✅ | R-12 |

---

## 6. Access control (IDOR) — decision table

> The item belongs to **User A**. Requests are sent on behalf of the user in the "Who" column.

| ID | Operation | Who | Item state | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|---|---|
| ACC-01 | PUT | User A | Exists | `200`, updated | ✅ | |
| ACC-02 | PUT | **User B** | Exists | `403`, `"Not your item"`; DB data **unchanged** | ✅ | |
| ACC-03 | PUT | User A | Deleted | `404` | ✅ | |
| ACC-04 | PUT | User B | Deleted | `404` | ✅ | |
| ACC-05 | PUT | User B | Does not exist | `404` | ✅ | |
| ACC-06 | DELETE | User A | Exists | `204`, `is_deleted = true` | ✅ | |
| ACC-07 | DELETE | **User B** | Exists | `403`, `"Not your item"`; in the DB `is_deleted = false` | ✅ | |
| ACC-08 | DELETE | User A | Deleted | `404` | ✅ | |
| ACC-09 | DELETE | User B | Deleted | `404` | ✅ | |
| ACC-10 | DELETE | User B | Does not exist | `404` | ✅ | |

**Additional access checks:**

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| ACC-11 | Enumerating other users' ids: User B sends `PUT` for ids 1…N | None of User A's items is modified | ✅ | |
| ACC-12 | Compare responses for someone else's item (`403`) and a non-existent one (`404`) | ❓ Different codes reveal which ids exist. Record as a remark; alternative — `404` in both cases | ❌ | Actual: someone else's item → 403, non-existent → 404 → **Q-06** |
| ACC-13 | User deleted from the DB, their token still valid → `POST /items/` | `401`, `"User not found"` | ✅ | |
| ACC-14 | Items of a deleted user in `GET /items/all` | ❓ Record the behaviour (orphans with `owner_id` without a user) | ⏭ | Actual: a user with items cannot be deleted: ERROR:  update or delete on table "users" violates foreign key constraint "items_owner_id_fk… → **[FAT-23](https://github.com/Requime31/fastapi-api-testing/issues/23)** |
| ACC-15 | Record in `logs` on `403` | `level = WARNING`, `message = item_update_forbidden` / `item_delete_forbidden`, `user_id` = the offender | ✅ | R-12 |

---

## 7. Contract and other

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CTR-01 | `GET /items/{item_id}` (get a single item) | The endpoint is not documented in the README. Record the actual response (`405`?) and the missing feature | ✅ | there is no endpoint to fetch a single item |
| CTR-02 | Unsupported methods: `PATCH /items/1`, `DELETE /items/`, `PUT /items/` | `405 Method Not Allowed` | ✅ | |
| CTR-03 | Responses match `/openapi.json` | Each endpoint documents the response schema and error codes. ❓ Items endpoints have no code descriptions in Swagger — record | ❌ | Actual: documented codes: {'GET /items/': ['200'], 'POST /items/': ['201', '422'], 'GET /items/all': ['200', '422'], 'PUT /items/{item_id… → **D-19** R-06 |
| CTR-04 | `Content-Type: application/json` for all responses (except `204`) | Yes | ✅ | |
| CTR-05 | Errors do not expose internals | No stack trace, SQL, file paths | ✅ | 500 responses are plain-text "Internal Server Error" without details |
| CTR-06 | Response time | ❓ All endpoints < 500 ms on the local stand | ✅ | |
| CTR-07 | Date format in the response (if `created_at` / `updated_at` are returned) | ISO 8601, ❓ with a time zone | ❌ | Actual: created_at = '2026-11-10T15:11:55.488475' → **D-20** R-05 |

---

## 8. E2E scenarios

| ID | Scenario | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| E2E-01 | Login → Create → `GET /items/` → Update → `GET /items/` → Delete → `GET /items/` | The item appears, is updated, disappears | ✅ | |
| E2E-02 | User A creates an item → User B tries Update and Delete → User A calls `GET /items/` | User B gets `403`; User A's data is unchanged | ✅ | |
| E2E-03 | Create 12 items → delete 3 → walk `GET /items/all` page by page | `total = 9`, no deleted items on any page | ❌ | Actual: user's items across all pages: 12 (expected 9), deleted ones visible: 3 → **D-13** R-04 |
| E2E-04 | Create → token refresh → Update with the new access token | `200`: the item is accessible after token rotation | ✅ | |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Create | 26 | 23 | 3 | 0 | 0 |
| 2. Get my items | 12 | 10 | 2 | 0 | 0 |
| 3. Get all (pagination) | 24 | 16 | 8 | 0 | 0 |
| 4. Update | 17 | 16 | 1 | 0 | 0 |
| 5. Delete | 12 | 11 | 1 | 0 | 0 |
| 6. Access control | 15 | 13 | 1 | 0 | 1 |
| 7. Contract | 7 | 5 | 2 | 0 | 0 |
| 8. E2E | 4 | 3 | 1 | 0 | 0 |
| **Total** | **117** | **97** | **19** | **0** | **1** |

Pass rate: **83.6%** (excluding ⏭). The module does not meet the exit criterion "≥ 95% passed".

**Defects found:** D-xx are working IDs until the defects are filed in Jira.

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| D-13 | PAG-13, PAG-14, PAG-15, DEL-05, E2E-03 | `GET /items/all` returns soft-deleted items and counts them in `total` / `pages` | Major |
| D-14 | PAG-16, PAG-17, PAG-18, PAG-19 | `GET /items/all`: `page ≤ 0` or `limit ≤ 0` cause `500 Internal Server Error` | Major |
| D-15 | PAG-20 | `GET /items/all`: no upper bound for `limit` — the whole table can be fetched in one request | Minor |
| D-16 | CRT-12, CRT-14, UPD-08 | Items: an empty or whitespace-only `title` is accepted on create and update | Minor |
| D-17 | CRT-04, MY-06 | Item responses expose internal fields (`owner_id`, `is_deleted`, `created_at`, `updated_at`) — `ItemResponse` is not used as `response_model` | Minor |
| D-18 | MY-07 | `GET /items/` and `GET /items/all` have no `ORDER BY` — the order changes after an update | Minor |
| D-19 | CTR-03 | Swagger: items endpoints have no descriptions, no error codes (401/403/404) and no response schemas | Minor |
| D-20 | CTR-07 | Timestamps are returned without a time zone (`2026-11-10T15:11:55.488475`) | Trivial |

**Questions to the developer (❓ checks):**

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| Q-05 | PAG-24 | `GET /items/all` shows every user's items (with `owner_id`) to any authenticated user. Is a public list of all items intended? | |
| Q-06 | ACC-12 | Someone else's item → `403`, a non-existent one → `404`: the difference reveals which ids exist. Should both return `404`? | |
| Q-07 | CRT-10 | `title` / `description` have no length limit (10,000 characters are accepted). What are the maximum lengths? | |
