# Checklist CL-02 — Items

| Field | Value |
|---|---|
| Module | Items: F-06…F-10 from the [Test Plan](../TEST_PLAN.md) |
| Endpoints | `POST /items/`, `GET /items/`, `GET /items/all`, `PUT /items/{item_id}`, `DELETE /items/{item_id}` |
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
| CRT-01 | Create with valid `title` and `description` | `201`; body contains `id`, `title`, `description` matching the request | H | | |
| CRT-02 | DB: record created correctly | `owner_id` = User A id, `is_deleted = false`, `created_at` and `updated_at` set (UTC, ≈ now) | H | | |
| CRT-03 | `id` is assigned automatically and is unique | Two consecutive creates → different `id`, the second is greater | M | | |
| CRT-04 | Response fields | ❓ The response matches the `ItemResponse` schema (`id`, `title`, `description`). Record if internal fields are returned (`owner_id`, `is_deleted`, `created_at`, …) | M | | R-05 |
| CRT-05 | The created item appears in `GET /items/` | The item is in User A's list | H | | |
| CRT-06 | Two items with the same `title` | `201` both times (uniqueness not required) | L | | |
| CRT-07 | Unicode and emoji: `"Заметка 📝"`, `"日本語"` | `201`; strings stored without distortion in the response and in the DB | M | | |
| CRT-08 | Special characters: `"<>&\"'/\\%"` | `201`; stored as is, without escaping or truncation | M | | |
| CRT-09 | 1-character string in both fields | `201` | L | | |
| CRT-10 | Long strings (1,000 and 10,000 characters) | ❓ `201` or `422` with a clear limit; no `500` | M | | R-02 |
| CRT-11 | Record in `logs` | `level = INFO`, `message = item_created`, `user_id`, `path = /items/`, `method = POST`, `status_code = 201` | L | | R-12 |

### 1.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CRT-12 | Empty `title: ""` | ❓ `422`: an item without a title makes no sense | M | | R-02 |
| CRT-13 | Empty `description: ""` | ❓ `422` or `201`. Record the behaviour | L | | R-02 |
| CRT-14 | `title` of spaces `"   "` | ❓ `422` | L | | R-02 |
| CRT-15 | `title` missing | `422`, `Field required`, `loc: ["body","title"]` | H | | |
| CRT-16 | `description` missing | `422`, `Field required` | H | | |
| CRT-17 | Empty body `{}` | `422` for both fields | M | | |
| CRT-18 | `title: null` | `422` | M | | |
| CRT-19 | Wrong types: `title: 123`, `title: true`, `title: ["a"]`, `title: {}` | `422` | M | | |
| CRT-20 | Invalid JSON / `Content-Type: text/plain` | `422`, no `500` | M | | |
| CRT-21 | Extra fields: `"owner_id": <User B id>`, `"is_deleted": true`, `"id": 9999` | Ignored: in the DB `owner_id` = User A, `is_deleted = false`, `id` auto-assigned (no mass assignment) | H | | |
| CRT-22 | HTML/JS in `title`: `"<script>alert(1)</script>"` | `201`, stored as text. ❓ Record as a stored XSS risk for a future frontend | L | | R-02 |
| CRT-23 | SQL injection in `title`: `"'; DROP TABLE items;--"` | `201`, stored as a string; `items` table intact; no `500` | M | | |
| CRT-24 | No `Authorization` header | `401` / `403`; item not created | H | | R-06 |
| CRT-25 | Invalid / expired token | `401`, `"Invalid or expired token"`; item not created | H | | |
| CRT-26 | Refresh token instead of access token in the header | `401` | M | | |

---

## 2. My items — `GET /items/` (F-07)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| MY-01 | User without items | `200`, `[]` | H | | |
| MY-02 | User with several items | `200`, array with all of the user's items | H | | |
| MY-03 | Data isolation | User A sees only their own items, User B's items are absent (and vice versa) | H | | |
| MY-04 | Deleted items are not returned | Delete an item → it is not in `GET /items/` | H | | R-04 |
| MY-05 | An updated item is returned with new data | After `PUT` the list contains the new `title` / `description` | M | | |
| MY-06 | Structure of each element | ❓ Fields as in `ItemResponse`; record extra fields | M | | R-05 |
| MY-07 | Element order | ❓ Deterministic (e.g. by `id` or `created_at`). Record the actual order | L | | |
| MY-08 | Large number of items (100+) | ❓ All returned without pagination, acceptable response time. Record as a growth risk | L | | |
| MY-09 | No token | `401` / `403` | H | | R-06 |
| MY-10 | Invalid token | `401` | H | | |
| MY-11 | Query parameters are ignored (`?owner_id=<User B id>`) | Only the current user's items are returned | M | | |
| MY-12 | Path without trailing slash `/items` | `200` or `307` redirect to `/items/`. ❓ Record whether `Authorization` is kept after the redirect | L | | |

---

## 3. All items with pagination — `GET /items/all` (F-08)

> Precondition: the DB contains exactly 25 items (item 4 of the module preconditions), 0 of them deleted unless stated otherwise.

### 3.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-01 | No parameters | `200`; `page = 1`, `limit = 10`, `total = 25`, `pages = 3`, 10 elements in `data` | H | | |
| PAG-02 | Response structure | Fields `page`, `limit`, `total`, `pages`, `data`; types: numbers and an array | H | | |
| PAG-03 | `page=2&limit=10` | 10 elements, no overlap with page 1 | H | | |
| PAG-04 | `page=3&limit=10` (last, partial) | 5 elements | H | | |
| PAG-05 | Walk through all pages | The union of `data` from all pages = 25 unique items, no duplicates or gaps | H | | |
| PAG-06 | `page=4&limit=10` (out of range) | `200`, `data = []`, `total = 25`. ❓ Or `404` — record | M | | R-03 |
| PAG-07 | `limit=1` (boundary) | 1 element, `pages = 25` | M | | R-03 |
| PAG-08 | `limit=25` (= total) | 25 elements, `pages = 1` | M | | |
| PAG-09 | `limit=100` (> total) | 25 elements, `pages = 1` | M | | |
| PAG-10 | Items of all users are returned | `data` contains items of both User A and User B | M | | |
| PAG-11 | Stable order | Two identical requests → the same order. ❓ Without `ORDER BY`, PostgreSQL does not guarantee the order — record | M | | |
| PAG-12 | Empty DB | `200`, `total = 0`, `pages = 0`, `data = []` | M | | |

### 3.2 Soft delete in pagination

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-13 | Delete 5 items → `GET /items/all?limit=100` | Deleted items are **absent** from `data` | H | | R-04 |
| PAG-14 | `total` after deleting 5 items | `total = 20`, `pages` recalculated | H | | R-04 |
| PAG-15 | Consistency of `GET /items/` and `GET /items/all` | Number of User A's items in `/items/all` = length of User A's `/items/` response | M | | R-04 |

### 3.3 Negative and boundary checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| PAG-16 | `page=0` | `422` (pages start at 1); no `500` | H | | R-03 |
| PAG-17 | `page=-1` | `422`; no `500` | H | | R-03 |
| PAG-18 | `limit=0` | `422`; no `500` | H | | R-03 |
| PAG-19 | `limit=-5` | `422`; no `500` | H | | R-03 |
| PAG-20 | `limit=100000` | ❓ Capped at a maximum (e.g. 100) or `422`. Record whether the whole table can be dumped in one request | M | | R-03 |
| PAG-21 | Non-numeric values: `page=abc`, `limit=1.5`, `page=` | `422` naming the parameter | M | | |
| PAG-22 | Very large `page=999999999999` | `200` with empty `data` or `422`; no `500` | L | | R-03 |
| PAG-23 | No token | `401` / `403` | H | | R-06 |
| PAG-24 | Visibility of other users' items | ❓ Any authenticated user sees all users' items. Clarify whether this is intended (README: "Get all items"). Check whether `owner_id` / email are exposed | M | | R-05 |

---

## 4. Update item — `PUT /items/{item_id}` (F-09)

### 4.1 Positive checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| UPD-01 | The owner updates their item | `200`; the response contains the new `title` and `description`, same `id` | H | | |
| UPD-02 | DB after the update | Data changed, `owner_id` and `created_at` unchanged, `updated_at` > `created_at` | H | | |
| UPD-03 | Update with the same values | `200`, data unchanged | L | | |
| UPD-04 | Repeated updates | `200` each time, the DB holds the last value | L | | |
| UPD-05 | Record in `logs` | `level = INFO`, `message = item_updated`, `status_code = 200` | L | | R-12 |

### 4.2 Negative checks

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| UPD-06 | Partial update: `title` only | `422` (PUT requires the full object). ❓ A partial update would be `PATCH` | M | | |
| UPD-07 | Empty body `{}` | `422` | M | | |
| UPD-08 | Invalid values (empty strings, `null`, wrong types) | Same rules as CRT-12…CRT-19 | M | | R-02 |
| UPD-09 | Attempt to change the owner: `"owner_id": <User B id>` in the body | Ignored: `owner_id` in the DB does not change | H | | |
| UPD-10 | Attempt to restore a deleted item: `"is_deleted": false` in the body | Ignored | M | | |
| UPD-11 | Non-existent `item_id` (e.g. 999999) | `404`, `"Item not found"` | H | | |
| UPD-12 | Deleted (soft delete) item | `404`; DB data unchanged | H | | R-04 |
| UPD-13 | Non-numeric `item_id` (`/items/abc`) | `422` | M | | |
| UPD-14 | `item_id = 0`, `-1` | `404` or `422`; no `500` | L | | |
| UPD-15 | `item_id` beyond int range (`99999999999999999999`) | `422` or `404`; no `500` | L | | |
| UPD-16 | No token | `401` / `403`; data unchanged | H | | R-06 |
| UPD-17 | Invalid token | `401`; data unchanged | H | | |

---

## 5. Delete item — `DELETE /items/{item_id}` (F-10)

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| DEL-01 | The owner deletes their item | `204 No Content` | H | | |
| DEL-02 | Body of the `204` response | Empty (per HTTP, `204` has no body). Check the Body tab and the `Content-Length` header | M | | R-06 |
| DEL-03 | Soft delete in the DB | The record **remains** in the table, `is_deleted = true` | H | | |
| DEL-04 | The deleted item disappears from `GET /items/` | Not in the list | H | | R-04 |
| DEL-05 | The deleted item disappears from `GET /items/all` | Not in `data`, `total` decreased | H | | R-04 |
| DEL-06 | Deleting the same item again | `404`, `"Item not found"` | H | | |
| DEL-07 | The user's other items are not affected | Delete 1 of 3 → 2 remain in the list | M | | |
| DEL-08 | Non-existent `item_id` | `404` | H | | |
| DEL-09 | Non-numeric `item_id` | `422` | M | | |
| DEL-10 | No token | `401` / `403`; item not deleted | H | | R-06 |
| DEL-11 | Invalid token | `401`; item not deleted | H | | |
| DEL-12 | Record in `logs` | `level = INFO`, `message = item_deleted`, `status_code = 204` | L | | R-12 |

---

## 6. Access control (IDOR) — decision table

> The item belongs to **User A**. Requests are sent on behalf of the user in the "Who" column.

| ID | Operation | Who | Item state | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|---|---|
| ACC-01 | PUT | User A | Exists | `200`, updated | H | | |
| ACC-02 | PUT | **User B** | Exists | `403`, `"Not your item"`; DB data **unchanged** | H | | |
| ACC-03 | PUT | User A | Deleted | `404` | H | | |
| ACC-04 | PUT | User B | Deleted | `404` | M | | |
| ACC-05 | PUT | User B | Does not exist | `404` | M | | |
| ACC-06 | DELETE | User A | Exists | `204`, `is_deleted = true` | H | | |
| ACC-07 | DELETE | **User B** | Exists | `403`, `"Not your item"`; in the DB `is_deleted = false` | H | | |
| ACC-08 | DELETE | User A | Deleted | `404` | H | | |
| ACC-09 | DELETE | User B | Deleted | `404` | M | | |
| ACC-10 | DELETE | User B | Does not exist | `404` | M | | |

**Additional access checks:**

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| ACC-11 | Enumerating other users' ids: User B sends `PUT` for ids 1…N | None of User A's items is modified | H | | |
| ACC-12 | Compare responses for someone else's item (`403`) and a non-existent one (`404`) | ❓ Different codes reveal which ids exist. Record as a remark; alternative — `404` in both cases | L | | |
| ACC-13 | User deleted from the DB, their token still valid → `POST /items/` | `401`, `"User not found"` | M | | |
| ACC-14 | Items of a deleted user in `GET /items/all` | ❓ Record the behaviour (orphans with `owner_id` without a user) | L | | |
| ACC-15 | Record in `logs` on `403` | `level = WARNING`, `message = item_update_forbidden` / `item_delete_forbidden`, `user_id` = the offender | L | | R-12 |

---

## 7. Contract and other

| ID | Check | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| CTR-01 | `GET /items/{item_id}` (get a single item) | The endpoint is not documented in the README. Record the actual response (`405`?) and the missing feature | L | | |
| CTR-02 | Unsupported methods: `PATCH /items/1`, `DELETE /items/`, `PUT /items/` | `405 Method Not Allowed` | L | | |
| CTR-03 | Responses match `/openapi.json` | Each endpoint documents the response schema and error codes. ❓ Items endpoints have no code descriptions in Swagger — record | M | | R-06 |
| CTR-04 | `Content-Type: application/json` for all responses (except `204`) | Yes | L | | |
| CTR-05 | Errors do not expose internals | No stack trace, SQL, file paths | H | | |
| CTR-06 | Response time | ❓ All endpoints < 500 ms on the local stand | L | | |
| CTR-07 | Date format in the response (if `created_at` / `updated_at` are returned) | ISO 8601, ❓ with a time zone | L | | R-05 |

---

## 8. E2E scenarios

| ID | Scenario | Expected result | Prio | Status | Comment / Bug |
|---|---|---|---|---|---|
| E2E-01 | Login → Create → `GET /items/` → Update → `GET /items/` → Delete → `GET /items/` | The item appears, is updated, disappears | H | | |
| E2E-02 | User A creates an item → User B tries Update and Delete → User A calls `GET /items/` | User B gets `403`; User A's data is unchanged | H | | |
| E2E-03 | Create 12 items → delete 3 → walk `GET /items/all` page by page | `total = 9`, no deleted items on any page | H | | R-04 |
| E2E-04 | Create → token refresh → Update with the new access token | `200`: the item is accessible after token rotation | M | | |

---

## Run summary

| Section | Total | ✅ | ❌ | ⚠️ | ⏭ |
|---|---|---|---|---|---|
| 1. Create | 26 | | | | |
| 2. Get my items | 12 | | | | |
| 3. Get all (pagination) | 24 | | | | |
| 4. Update | 17 | | | | |
| 5. Delete | 12 | | | | |
| 6. Access control | 15 | | | | |
| 7. Contract | 7 | | | | |
| 8. E2E | 4 | | | | |
| **Total** | **117** | | | | |

**Defects found:**

| Jira / GitHub | Check | Title | Severity |
|---|---|---|---|
| | | | |

**Questions to the developer (❓ checks):**

| Jira / GitHub | Check | Question | Answer |
|---|---|---|---|
| | | | |
