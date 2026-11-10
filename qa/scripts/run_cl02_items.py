"""
Executes checklist CL-02 Items (docs/checklists/CL-02_Items.md) against the local stand.

The pagination section needs an items table with exactly 25 rows: the script copies
the current items to a backup table, clears `items` for that section and restores it
afterwards, so the stand's existing data is preserved.

Requirements: stand started with qa/docker-compose.functional.yml; pip install httpx python-jose
Usage: python qa/scripts/run_cl02_items.py      # results → qa/runs/CL-02_<date>.json
"""
import sys
import time

from common import (body, bearer, check, client, email, health_ok, login, new_user, register, req,
                    save, section, short, sql, sql1, timings)

ITEM_KEYS = {"id", "title", "description"}
S = {}  # shared state between sections


def create(tok, title="Item", description="Description"):
    return req("POST", "/items/", json_body={"title": title, "description": description}, headers=bearer(tok))


def item_row(item_id):
    rows = sql(f"SELECT owner_id, title, description, is_deleted, created_at, updated_at FROM items WHERE id={item_id};")
    return rows[0] if rows else None


def last_item_log(uid, message):
    rows = sql(f"SELECT level, message, path, coalesce(method,''), coalesce(status_code::text,''), coalesce(user_id::text,'') "
               f"FROM logs WHERE user_id={uid} AND message='{message}' ORDER BY id DESC LIMIT 1;")
    return rows[0] if rows else None


# ───────────────────────── 1. Create ─────────────────────────

def s_create():
    ea, ua, ta, _ = new_user("itemA")
    eb, ub, tb, rb = new_user("itemB")
    S.update(ua=ua, ta=ta, ub=ub, tb=tb, rb=rb)

    r = create(ta, "First item", "First description")
    b = body(r)
    check("CRT-01", r.status_code == 201 and b.get("title") == "First item" and b.get("description") == "First description"
          and isinstance(b.get("id"), int), short(r))
    iid = b["id"]
    S["first_item"] = b

    row = item_row(iid)
    age = float(sql1(f"SELECT abs(extract(epoch from (now() at time zone 'utc' - created_at))) FROM items WHERE id={iid};"))
    check("CRT-02", row[0] == str(ua) and row[3] == "f" and row[4] and row[5] and age < 120,
          f"owner_id={row[0]} (user {ua}), is_deleted={row[3]}, created_at={row[4]}, updated_at={row[5]}, age {age:.0f} s")

    i2 = body(create(ta, "Second"))["id"]
    i3 = body(create(ta, "Third"))["id"]
    check("CRT-03", i3 > i2 > iid, f"ids: {iid}, {i2}, {i3}")

    keys = set(b)
    extra = sorted(keys - ITEM_KEYS)
    check("CRT-04", keys == ITEM_KEYS, f"response fields: {sorted(keys)}",
          "" if not extra else f"internal fields are returned: {extra}; the ItemResponse schema is not used as response_model")

    lst = body(req("GET", "/items/", headers=bearer(ta)))
    check("CRT-05", any(x["id"] == iid for x in lst), f"item {iid} in GET /items/: {any(x['id'] == iid for x in lst)}")

    c = [create(ta, "Same title").status_code, create(ta, "Same title").status_code]
    check("CRT-06", c == [201, 201], f"codes: {c}")

    vals = ["Заметка 📝", "日本語"]
    ok, got = True, []
    for v in vals:
        rr = create(ta, v, v)
        stored = sql1(f"SELECT title FROM items WHERE id={body(rr)['id']};")
        ok &= rr.status_code == 201 and body(rr)["title"] == v and stored == v
        got.append((rr.status_code, stored))
    check("CRT-07", ok, f"(code, stored title) = {got}")

    sp = "<>&\"'/\\%"
    rr = create(ta, sp, sp)
    stored = sql1(f"SELECT title FROM items WHERE id={body(rr)['id']};")
    check("CRT-08", rr.status_code == 201 and body(rr)["title"] == sp and stored == sp, f"{rr.status_code}; stored = {stored}")

    rr = create(ta, "a", "b")
    check("CRT-09", rr.status_code == 201, short(rr))

    got = {}
    for n in (1000, 10000):
        rr = create(ta, "t" * n, "d" * n)
        got[n] = rr.status_code
    check("CRT-10", all(c in (201, 422) for c in got.values()), f"length → code: {got}",
          "no length limit: 10,000-character strings are accepted" if got.get(10000) == 201 else "")

    lg = last_item_log(ua, "item_created")
    check("CRT-11", lg is not None and lg[0] == "INFO" and lg[2] == "/items/" and lg[3] == "POST" and lg[4] == "201"
          and lg[5] == str(ua), f"logs: {lg}")

    rr = create(ta, "", "desc")
    check("CRT-12", rr.status_code == 422, short(rr), "" if rr.status_code == 422 else "an item with an empty title is created")
    S["empty_title_code"] = rr.status_code

    rr = create(ta, "Title", "")
    check("CRT-13", rr.status_code in (201, 422), short(rr),
          "an empty description is accepted" if rr.status_code == 201 else "")

    rr = create(ta, "   ", "desc")
    check("CRT-14", rr.status_code == 422, short(rr), "" if rr.status_code == 422 else "a whitespace-only title is accepted")

    rr = req("POST", "/items/", json_body={"description": "d"}, headers=bearer(ta))
    check("CRT-15", rr.status_code == 422 and any(x.get("loc") == ["body", "title"] for x in body(rr).get("detail", [])), short(rr))

    rr = req("POST", "/items/", json_body={"title": "t"}, headers=bearer(ta))
    check("CRT-16", rr.status_code == 422 and "Field required" in rr.text, short(rr))

    rr = req("POST", "/items/", json_body={}, headers=bearer(ta))
    locs = [x.get("loc") for x in body(rr).get("detail", [])] if rr.status_code == 422 else []
    check("CRT-17", ["body", "title"] in locs and ["body", "description"] in locs, f"{rr.status_code}; loc = {locs}")

    rr = req("POST", "/items/", json_body={"title": None, "description": "d"}, headers=bearer(ta))
    check("CRT-18", rr.status_code == 422, short(rr))

    got = {repr(v): req("POST", "/items/", json_body={"title": v, "description": "d"}, headers=bearer(ta)).status_code
           for v in (123, True, ["a"], {})}
    check("CRT-19", all(c == 422 for c in got.values()), str(got))

    r1 = req("POST", "/items/", content='{"title": "t",', headers={**bearer(ta), "Content-Type": "application/json"})
    r2 = req("POST", "/items/", content="title=t", headers={**bearer(ta), "Content-Type": "text/plain"})
    check("CRT-20", r1.status_code == 422 and r2.status_code == 422, f"broken JSON → {r1.status_code}, text/plain → {r2.status_code}")

    rr = req("POST", "/items/", json_body={"title": "Mass", "description": "d", "owner_id": ub, "is_deleted": True, "id": 999999},
             headers=bearer(ta))
    row = item_row(body(rr)["id"]) if rr.status_code == 201 else None
    check("CRT-21", rr.status_code == 201 and body(rr)["id"] != 999999 and row[0] == str(ua) and row[3] == "f",
          f"{rr.status_code}; id={body(rr).get('id')}, owner_id={row[0] if row else None}, is_deleted={row[3] if row else None}")

    rr = create(ta, "<script>alert(1)</script>", "x")
    check("CRT-22", rr.status_code == 201 and body(rr)["title"] == "<script>alert(1)</script>", short(rr),
          "HTML/JS is stored and returned as is — stored XSS risk for a future frontend (output encoding is the frontend's job)")

    rr = create(ta, "'; DROP TABLE items;--", "x")
    exists = sql1("SELECT to_regclass('public.items') IS NOT NULL;")
    check("CRT-23", rr.status_code == 201 and exists == "t", f"{rr.status_code}; items table exists: {exists}")

    before = sql1("SELECT count(*) FROM items;")
    rr = req("POST", "/items/", json_body={"title": "noauth", "description": "d"})
    after = sql1("SELECT count(*) FROM items;")
    check("CRT-24", rr.status_code in (401, 403) and before == after, f"{short(rr)}; items {before}→{after}",
          "" if rr.status_code == 401 else "403 instead of 401 — same root cause as FAT-13")

    rr = req("POST", "/items/", json_body={"title": "bad", "description": "d"}, headers=bearer("x.y.z"))
    check("CRT-25", rr.status_code == 401 and body(rr) == {"detail": "Invalid or expired token"}, short(rr))

    rr = req("POST", "/items/", json_body={"title": "bad", "description": "d"}, headers=bearer(rb))
    check("CRT-26", rr.status_code == 401, short(rr))


# ───────────────────────── 2. My items ─────────────────────────

def s_my_items():
    _, uc, tc, _ = new_user("myC")
    r = req("GET", "/items/", headers=bearer(tc))
    check("MY-01", r.status_code == 200 and body(r) == [], short(r))

    ids = [body(create(tc, f"C{i}"))["id"] for i in range(3)]
    lst = body(req("GET", "/items/", headers=bearer(tc)))
    check("MY-02", sorted(x["id"] for x in lst) == sorted(ids), f"created {ids}, returned {[x['id'] for x in lst]}")

    a_ids = {x["id"] for x in body(req("GET", "/items/", headers=bearer(S["ta"])))}
    b_ids = {x["id"] for x in body(req("GET", "/items/", headers=bearer(S["tb"])))}
    c_ids = {x["id"] for x in lst}
    check("MY-03", not (a_ids & c_ids) and not (b_ids & c_ids) and not (a_ids & b_ids),
          f"overlaps A∩C={len(a_ids & c_ids)}, B∩C={len(b_ids & c_ids)}, A∩B={len(a_ids & b_ids)}")

    req("DELETE", f"/items/{ids[0]}", headers=bearer(tc))
    lst = body(req("GET", "/items/", headers=bearer(tc)))
    check("MY-04", ids[0] not in [x["id"] for x in lst], f"deleted {ids[0]} in list: {ids[0] in [x['id'] for x in lst]}")

    req("PUT", f"/items/{ids[1]}", json_body={"title": "C1 updated", "description": "new"}, headers=bearer(tc))
    lst = body(req("GET", "/items/", headers=bearer(tc)))
    upd = next((x for x in lst if x["id"] == ids[1]), {})
    check("MY-05", upd.get("title") == "C1 updated" and upd.get("description") == "new", f"item {ids[1]}: {upd.get('title')!r}")

    keys = set(lst[0]) if lst else set()
    check("MY-06", keys == {"id", "title", "description"}, f"element fields: {sorted(keys)}",
          "" if keys == {"id", "title", "description"} else "internal fields are returned (owner_id, is_deleted, timestamps)")

    order = [x["id"] for x in lst]
    check("MY-07", order == sorted(order), f"order after an update: {order}",
          "" if order == sorted(order) else "no ORDER BY: an updated row moves to the end — the order is not deterministic")

    _, ud, td, _ = new_user("myD")
    for i in range(100):
        create(td, f"D{i}")
    t0 = time.perf_counter()
    r = req("GET", "/items/", headers=bearer(td))
    ms = (time.perf_counter() - t0) * 1000
    check("MY-08", r.status_code == 200 and len(body(r)) == 100 and ms < 1000, f"100 items returned: {len(body(r))}, {ms:.0f} ms",
          "the endpoint has no pagination — the response grows with the number of items")

    r = req("GET", "/items/")
    check("MY-09", r.status_code in (401, 403), short(r), "" if r.status_code == 401 else "403 instead of 401 — see FAT-13")

    r = req("GET", "/items/", headers=bearer("x.y.z"))
    check("MY-10", r.status_code == 401, short(r))

    r = req("GET", "/items/", params={"owner_id": S["ua"]}, headers=bearer(tc))
    check("MY-11", {x["id"] for x in body(r)} == c_ids - {ids[0]}, f"?owner_id=<User A> → returned own items only: "
          f"{({x['id'] for x in body(r)} == c_ids - {ids[0]})}")

    r = req("GET", "/items", headers=bearer(tc))
    loc = r.headers.get("location")
    note = ""
    if r.status_code in (307, 308) and loc:
        r2 = client.get(loc, headers=bearer(tc))
        note = f"redirect to {loc}; following with the same Authorization → {r2.status_code}"
    check("MY-12", r.status_code in (200, 307, 308), f"{r.status_code}", note)


# ───────────────────────── 3. Pagination ─────────────────────────

def all_items(tok, **params):
    return req("GET", "/items/all", params=params or None, headers=bearer(tok))


def s_pagination():
    sql("DROP TABLE IF EXISTS qa_items_backup; CREATE TABLE qa_items_backup AS SELECT * FROM items; DELETE FROM items;")
    try:
        _pagination_body()
    finally:
        sql("DELETE FROM items; INSERT INTO items SELECT * FROM qa_items_backup; DROP TABLE qa_items_backup;")
        print("   items table restored from backup", flush=True)


def _pagination_body():
    ta, tb = S["ta"], S["tb"]
    r = all_items(ta)
    b = body(r)
    check("PAG-12", r.status_code == 200 and b.get("total") == 0 and b.get("pages") == 0 and b.get("data") == [], short(r))

    a_ids = [body(create(ta, f"A{i}"))["id"] for i in range(15)]
    b_ids = [body(create(tb, f"B{i}"))["id"] for i in range(10)]

    r = all_items(ta)
    b = body(r)
    check("PAG-01", r.status_code == 200 and b.get("page") == 1 and b.get("limit") == 10 and b.get("total") == 25
          and b.get("pages") == 3 and len(b.get("data", [])) == 10,
          f"page={b.get('page')}, limit={b.get('limit')}, total={b.get('total')}, pages={b.get('pages')}, len(data)={len(b.get('data', []))}")

    types_ok = all(isinstance(b.get(k), int) for k in ("page", "limit", "total", "pages")) and isinstance(b.get("data"), list)
    check("PAG-02", set(b) == {"page", "limit", "total", "pages", "data"} and types_ok, f"keys={sorted(b)}, types ok={types_ok}")

    p1 = [x["id"] for x in b["data"]]
    p2 = [x["id"] for x in body(all_items(ta, page=2, limit=10))["data"]]
    check("PAG-03", len(p2) == 10 and not set(p1) & set(p2), f"page 2: {len(p2)} items, overlap with page 1: {len(set(p1) & set(p2))}")

    p3 = [x["id"] for x in body(all_items(ta, page=3, limit=10))["data"]]
    check("PAG-04", len(p3) == 5, f"page 3: {len(p3)} items")

    union = p1 + p2 + p3
    check("PAG-05", len(union) == 25 and set(union) == set(a_ids + b_ids), f"{len(union)} ids, {len(set(union))} unique, "
          f"all created present: {set(union) == set(a_ids + b_ids)}")

    r = all_items(ta, page=4, limit=10)
    b = body(r)
    check("PAG-06", r.status_code == 200 and b.get("data") == [] and b.get("total") == 25, short(r, 120))

    b = body(all_items(ta, limit=1))
    check("PAG-07", len(b["data"]) == 1 and b["pages"] == 25, f"len={len(b['data'])}, pages={b['pages']}")

    b = body(all_items(ta, limit=25))
    check("PAG-08", len(b["data"]) == 25 and b["pages"] == 1, f"len={len(b['data'])}, pages={b['pages']}")

    b = body(all_items(ta, limit=100))
    check("PAG-09", len(b["data"]) == 25 and b["pages"] == 1, f"len={len(b['data'])}, pages={b['pages']}")

    ids = {x["id"] for x in b["data"]}
    check("PAG-10", bool(ids & set(a_ids)) and bool(ids & set(b_ids)),
          f"User A items: {len(ids & set(a_ids))}, User B items: {len(ids & set(b_ids))}")

    o1 = [x["id"] for x in body(all_items(ta, limit=100))["data"]]
    o2 = [x["id"] for x in body(all_items(ta, limit=100))["data"]]
    check("PAG-11", o1 == o2, f"two identical requests return the same order: {o1 == o2}",
          "the query has no ORDER BY — stable here, but PostgreSQL does not guarantee the order (e.g. after updates)")

    deleted = a_ids[:5]
    for i in deleted:
        req("DELETE", f"/items/{i}", headers=bearer(ta))
    b = body(all_items(ta, limit=100))
    present = [i for i in deleted if i in {x["id"] for x in b["data"]}]
    check("PAG-13", not present, f"deleted items still in data: {len(present)} of 5",
          "" if not present else "soft-deleted items are returned by /items/all (no is_deleted filter)")
    S["pag_deleted_visible"] = bool(present)

    check("PAG-14", b["total"] == 20, f"total after deleting 5 = {b['total']}, pages = {b['pages']}",
          "" if b["total"] == 20 else "total counts soft-deleted items")

    mine = len(body(req("GET", "/items/", headers=bearer(ta))))
    in_all = len({x["id"] for x in b["data"]} & set(a_ids))
    check("PAG-15", mine == in_all, f"User A: GET /items/ → {mine}, User A items in /items/all → {in_all}")

    got = {}
    for name, params in [("page=0", {"page": 0}), ("page=-1", {"page": -1}), ("limit=0", {"limit": 0}), ("limit=-5", {"limit": -5})]:
        r = all_items(ta, **params)
        got[name] = r
    for cid, name in [("PAG-16", "page=0"), ("PAG-17", "page=-1"), ("PAG-18", "limit=0"), ("PAG-19", "limit=-5")]:
        r = got[name]
        check(cid, r.status_code == 422, f"{name} → {short(r, 80)}",
              "" if r.status_code == 422 else ("unhandled server error (no input validation)" if r.status_code == 500 else ""))

    r = all_items(ta, limit=100000)
    b = body(r)
    capped = r.status_code == 422 or (r.status_code == 200 and len(b.get("data", [])) <= 100 and b.get("limit", 0) <= 100)
    check("PAG-20", capped, f"limit=100000 → {r.status_code}, limit in response={b.get('limit') if isinstance(b, dict) else None}, "
          f"returned {len(b.get('data', [])) if isinstance(b, dict) else '-'} (all rows)",
          "" if capped else "no upper bound on limit: the whole table can be fetched in one request")

    got = {k: all_items(ta, **v).status_code for k, v in [("page=abc", {"page": "abc"}), ("limit=1.5", {"limit": "1.5"}), ("page=", {"page": ""})]}
    check("PAG-21", all(c == 422 for c in got.values()), str(got))

    r = all_items(ta, page=999999999999)
    check("PAG-22", r.status_code in (200, 422), short(r, 100))

    r = req("GET", "/items/all")
    check("PAG-23", r.status_code in (401, 403), short(r), "" if r.status_code == 401 else "403 instead of 401 — see FAT-13")

    sample = body(all_items(tb, limit=100))["data"][0]
    leaks = [k for k in sample if k in ("owner_id", "email")]
    check("PAG-24", "email" not in sample, f"element fields: {sorted(sample)}",
          f"any user sees all users' items with {leaks} — confirm that a public list of all items is intended")


# ───────────────────────── 4. Update ─────────────────────────

def s_update():
    ta, tb, ua, ub = S["ta"], S["tb"], S["ua"], S["ub"]
    iid = body(create(ta, "Before", "before"))["id"]
    created = sql1(f"SELECT created_at FROM items WHERE id={iid};")
    time.sleep(1)

    r = req("PUT", f"/items/{iid}", json_body={"title": "After", "description": "after"}, headers=bearer(ta))
    check("UPD-01", r.status_code == 200 and body(r).get("id") == iid and body(r).get("title") == "After", short(r))

    row = sql(f"SELECT owner_id, title, created_at, updated_at, updated_at > created_at FROM items WHERE id={iid};")[0]
    check("UPD-02", row[0] == str(ua) and row[1] == "After" and row[2] == created and row[4] == "t",
          f"owner_id={row[0]}, title={row[1]}, created_at unchanged={row[2] == created}, updated_at > created_at: {row[4]}")

    r = req("PUT", f"/items/{iid}", json_body={"title": "After", "description": "after"}, headers=bearer(ta))
    check("UPD-03", r.status_code == 200, short(r))

    for i in range(3):
        req("PUT", f"/items/{iid}", json_body={"title": f"V{i}", "description": "d"}, headers=bearer(ta))
    check("UPD-04", sql1(f"SELECT title FROM items WHERE id={iid};") == "V2", f"title in DB = {sql1(f'SELECT title FROM items WHERE id={iid};')}")

    lg = last_item_log(ua, "item_updated")
    check("UPD-05", lg is not None and lg[0] == "INFO" and lg[4] == "200", f"logs: {lg}")

    r = req("PUT", f"/items/{iid}", json_body={"title": "Only title"}, headers=bearer(ta))
    check("UPD-06", r.status_code == 422, short(r))

    r = req("PUT", f"/items/{iid}", json_body={}, headers=bearer(ta))
    check("UPD-07", r.status_code == 422, short(r))

    got = {repr(v): req("PUT", f"/items/{iid}", json_body={"title": v, "description": "d"}, headers=bearer(ta)).status_code
           for v in ("", None, 123)}
    consistent = got["None"] == 422 and got["123"] == 422 and got["''"] == S.get("empty_title_code")
    check("UPD-08", got["''"] == 422 and got["None"] == 422 and got["123"] == 422, f"title → code: {got}",
          "" if got["''"] == 422 else "an empty title is accepted on update as well (same as CRT-12)")
    req("PUT", f"/items/{iid}", json_body={"title": "V2", "description": "d"}, headers=bearer(ta))

    r = req("PUT", f"/items/{iid}", json_body={"title": "Own", "description": "d", "owner_id": ub}, headers=bearer(ta))
    check("UPD-09", sql1(f"SELECT owner_id FROM items WHERE id={iid};") == str(ua),
          f"{r.status_code}; owner_id in DB = {sql1(f'SELECT owner_id FROM items WHERE id={iid};')}")

    did = body(create(ta, "To delete"))["id"]
    req("DELETE", f"/items/{did}", headers=bearer(ta))
    r = req("PUT", f"/items/{did}", json_body={"title": "Revive", "description": "d", "is_deleted": False}, headers=bearer(ta))
    row = sql(f"SELECT is_deleted, title FROM items WHERE id={did};")[0]
    check("UPD-10", r.status_code == 404 and row[0] == "t", f"{r.status_code}; is_deleted={row[0]}")
    check("UPD-12", r.status_code == 404 and row[1] == "To delete", f"{short(r)}; title in DB unchanged: {row[1] == 'To delete'}")

    r = req("PUT", "/items/999999999", json_body={"title": "x", "description": "d"}, headers=bearer(ta))
    check("UPD-11", r.status_code == 404 and body(r) == {"detail": "Item not found"}, short(r))

    r = req("PUT", "/items/abc", json_body={"title": "x", "description": "d"}, headers=bearer(ta))
    check("UPD-13", r.status_code == 422, short(r, 100))

    got = {i: req("PUT", f"/items/{i}", json_body={"title": "x", "description": "d"}, headers=bearer(ta)).status_code for i in (0, -1)}
    check("UPD-14", all(c in (404, 422) for c in got.values()), str(got))

    r = req("PUT", "/items/99999999999999999999", json_body={"title": "x", "description": "d"}, headers=bearer(ta))
    check("UPD-15", r.status_code in (404, 422), short(r, 120), "" if r.status_code != 500 else "out-of-range id causes a server error")
    S["upd15"] = r.status_code

    before = sql1(f"SELECT title FROM items WHERE id={iid};")
    r1 = req("PUT", f"/items/{iid}", json_body={"title": "hack", "description": "d"})
    r2 = req("PUT", f"/items/{iid}", json_body={"title": "hack", "description": "d"}, headers=bearer("x.y.z"))
    after = sql1(f"SELECT title FROM items WHERE id={iid};")
    check("UPD-16", r1.status_code in (401, 403) and before == after, f"{r1.status_code}; title unchanged: {before == after}",
          "" if r1.status_code == 401 else "403 instead of 401 — see FAT-13")
    check("UPD-17", r2.status_code == 401 and before == after, f"{short(r2)}; title unchanged: {before == after}")


# ───────────────────────── 5. Delete ─────────────────────────

def s_delete():
    ta, ua = S["ta"], S["ua"]
    ids = [body(create(ta, f"Del{i}"))["id"] for i in range(3)]
    total_before = body(all_items(ta))["total"]

    r = req("DELETE", f"/items/{ids[0]}", headers=bearer(ta))
    check("DEL-01", r.status_code == 204, short(r))
    cl = r.headers.get("content-length")
    check("DEL-02", r.content == b"" and cl in (None, "0"), f"body={r.content[:60]!r}, Content-Length={cl}",
          "" if r.content == b"" else "204 response has a body")

    row = sql(f"SELECT is_deleted FROM items WHERE id={ids[0]};")
    check("DEL-03", row and row[0][0] == "t", f"record exists: {bool(row)}, is_deleted={row[0][0] if row else None}")

    mine = [x["id"] for x in body(req("GET", "/items/", headers=bearer(ta)))]
    check("DEL-04", ids[0] not in mine, f"deleted item in GET /items/: {ids[0] in mine}")

    b = body(all_items(ta, limit=100000))
    in_all = ids[0] in {x["id"] for x in b["data"]}
    check("DEL-05", not in_all and b["total"] == total_before - 1,
          f"in /items/all: {in_all}; total {total_before} → {b['total']}",
          "" if not in_all else "the deleted item stays in /items/all and in total (see PAG-13/14)")

    r = req("DELETE", f"/items/{ids[0]}", headers=bearer(ta))
    check("DEL-06", r.status_code == 404 and body(r) == {"detail": "Item not found"}, short(r))

    check("DEL-07", ids[1] in mine and ids[2] in mine, f"other items still listed: {ids[1] in mine and ids[2] in mine}")

    r = req("DELETE", "/items/999999999", headers=bearer(ta))
    check("DEL-08", r.status_code == 404, short(r))

    r = req("DELETE", "/items/abc", headers=bearer(ta))
    check("DEL-09", r.status_code == 422, short(r, 100))

    r1 = req("DELETE", f"/items/{ids[1]}")
    r2 = req("DELETE", f"/items/{ids[1]}", headers=bearer("x.y.z"))
    alive = sql1(f"SELECT NOT is_deleted FROM items WHERE id={ids[1]};") == "t"
    check("DEL-10", r1.status_code in (401, 403) and alive, f"{r1.status_code}; item not deleted: {alive}",
          "" if r1.status_code == 401 else "403 instead of 401 — see FAT-13")
    check("DEL-11", r2.status_code == 401 and alive, f"{short(r2)}; item not deleted: {alive}")

    lg = last_item_log(ua, "item_deleted")
    check("DEL-12", lg is not None and lg[0] == "INFO" and lg[4] == "204", f"logs: {lg}")


# ───────────────────────── 6. Access control ─────────────────────────

def s_access():
    ta, tb, ua, ub = S["ta"], S["tb"], S["ua"], S["ub"]
    put = lambda i, tok, t="x": req("PUT", f"/items/{i}", json_body={"title": t, "description": "d"}, headers=bearer(tok))
    dele = lambda i, tok: req("DELETE", f"/items/{i}", headers=bearer(tok))

    i1 = body(create(ta, "ACC owner"))["id"]
    r = put(i1, ta, "ACC updated")
    check("ACC-01", r.status_code == 200 and sql1(f"SELECT title FROM items WHERE id={i1};") == "ACC updated", short(r))

    r = put(i1, tb, "hacked")
    check("ACC-02", r.status_code == 403 and body(r) == {"detail": "Not your item"} and sql1(f"SELECT title FROM items WHERE id={i1};") == "ACC updated",
          f"{short(r)}; data unchanged: {sql1(f'SELECT title FROM items WHERE id={i1};') == 'ACC updated'}")

    i2 = body(create(ta, "ACC deleted"))["id"]
    dele(i2, ta)
    check("ACC-03", put(i2, ta).status_code == 404, "PUT deleted by owner → " + str(put(i2, ta).status_code))
    check("ACC-04", put(i2, tb).status_code == 404, "PUT deleted by other user → " + str(put(i2, tb).status_code))
    check("ACC-05", put(999999999, tb).status_code == 404, "PUT non-existent by other user → " + str(put(999999999, tb).status_code))

    i3 = body(create(ta, "ACC del"))["id"]
    r = dele(i3, ta)
    check("ACC-06", r.status_code == 204 and sql1(f"SELECT is_deleted FROM items WHERE id={i3};") == "t", f"{r.status_code}; is_deleted=t")

    i4 = body(create(ta, "ACC keep"))["id"]
    r = dele(i4, tb)
    check("ACC-07", r.status_code == 403 and body(r) == {"detail": "Not your item"} and sql1(f"SELECT is_deleted FROM items WHERE id={i4};") == "f",
          f"{short(r)}; is_deleted={sql1(f'SELECT is_deleted FROM items WHERE id={i4};')}")

    check("ACC-08", dele(i3, ta).status_code == 404, "DELETE deleted by owner → " + str(dele(i3, ta).status_code))
    check("ACC-09", dele(i3, tb).status_code == 404, "DELETE deleted by other user → " + str(dele(i3, tb).status_code))
    check("ACC-10", dele(999999999, tb).status_code == 404, "DELETE non-existent by other user → " + str(dele(999999999, tb).status_code))

    a_ids = [int(x[0]) for x in sql(f"SELECT id FROM items WHERE owner_id={ua} AND NOT is_deleted ORDER BY id;")]
    snap = sql(f"SELECT id, title, description FROM items WHERE owner_id={ua} ORDER BY id;")
    codes = {}
    for i in a_ids:
        c = put(i, tb, "pwned").status_code
        codes[c] = codes.get(c, 0) + 1
    after = sql(f"SELECT id, title, description FROM items WHERE owner_id={ua} ORDER BY id;")
    check("ACC-11", snap == after, f"User B PUT over {len(a_ids)} User A items → codes {sorted(set(codes))}; data unchanged: {snap == after}")

    c403, c404 = put(i4, tb).status_code, put(999999999, tb).status_code
    check("ACC-12", c403 == c404, f"someone else's item → {c403}, non-existent → {c404}",
          "" if c403 == c404 else "different codes reveal which item ids exist (low risk: ids are also visible in /items/all)")

    e, uid, tok, _ = new_user("accdel")
    sql(f"DELETE FROM refresh_tokens WHERE user_id={uid}; DELETE FROM users WHERE id={uid};")
    r = create(tok, "ghost")
    check("ACC-13", r.status_code == 401 and body(r) == {"detail": "User not found"}, short(r))

    e, uid, tok, _ = new_user("accorphan")
    create(tok, "orphan")
    try:
        sql(f"DELETE FROM refresh_tokens WHERE user_id={uid}; DELETE FROM users WHERE id={uid};")
        check("ACC-14", True, "user with items deleted")
    except RuntimeError as ex:
        check("ACC-14", True, "a user with items cannot be deleted: " + str(ex).splitlines()[0][:110],
              "FK items.owner_id has no ON DELETE CASCADE — orphan items cannot appear; see FAT-23", status="skip")

    put(i4, tb)
    lg = sql(f"SELECT level, message, coalesce(user_id::text,''), coalesce(status_code::text,'') FROM logs "
             f"WHERE message IN ('item_update_forbidden','item_delete_forbidden') AND user_id={ub} ORDER BY id DESC LIMIT 1;")
    check("ACC-15", bool(lg) and lg[0][0] == "WARNING" and lg[0][2] == str(ub) and lg[0][3] == "403", f"logs: {lg[0] if lg else None}")


# ───────────────────────── 7. Contract ─────────────────────────

def s_contract():
    ta = S["ta"]
    iid = body(create(ta, "Contract"))["id"]
    r = req("GET", f"/items/{iid}", headers=bearer(ta))
    check("CTR-01", True, f"GET /items/{{id}} → {short(r, 80)}", "there is no endpoint to fetch a single item")

    got = {"PATCH /items/1": req("PATCH", f"/items/{iid}", json_body={}, headers=bearer(ta)).status_code,
           "DELETE /items/": req("DELETE", "/items/", headers=bearer(ta)).status_code,
           "PUT /items/": req("PUT", "/items/", json_body={}, headers=bearer(ta)).status_code}
    check("CTR-02", all(c == 405 for c in got.values()), str(got))

    spec = client.get("/openapi.json").json()
    doc = {}
    for path, ops in spec["paths"].items():
        if path.startswith("/items"):
            for m, op in ops.items():
                doc[f"{m.upper()} {path}"] = sorted(op.get("responses", {}))
    has_errors = all(any(c in codes for c in ("401", "403", "404")) for codes in doc.values())
    check("CTR-03", has_errors, f"documented codes: {doc}",
          "" if has_errors else "items endpoints document only the success code and 422 — no 401/403/404, no response schema")

    samples = {"POST /items/": create(ta, "ct"), "GET /items/": req("GET", "/items/", headers=bearer(ta)),
               "GET /items/all": all_items(ta), "PUT 404": req("PUT", "/items/999999999", json_body={"title": "x", "description": "d"}, headers=bearer(ta)),
               "DELETE 404": req("DELETE", "/items/999999999", headers=bearer(ta))}
    ct = {k: v.headers.get("content-type") for k, v in samples.items()}
    check("CTR-04", all(v and v.startswith("application/json") for v in ct.values()), str(ct))

    probes = [all_items(ta, page=0), all_items(ta, limit=0), req("PUT", "/items/abc", json_body={}, headers=bearer(ta))]
    if S.get("upd15") == 500:
        probes.append(req("PUT", "/items/99999999999999999999", json_body={"title": "x", "description": "d"}, headers=bearer(ta)))
    leaks = [p.status_code for p in probes if any(k in p.text for k in ("Traceback", "sqlalchemy", "psycopg", "/app/", "File \""))]
    check("CTR-05", not leaks, f"error responses checked: {[p.status_code for p in probes]}; with internals: {leaks}",
          "500 responses are plain-text \"Internal Server Error\" without details")

    slow = {k: round(max(v)) for k, v in timings.items() if k.startswith(("GET /items", "POST /items", "PUT /items", "DELETE /items")) and max(v) > 500}
    worst = {k: round(sorted(v)[len(v) // 2]) for k, v in timings.items() if "/items" in k}
    check("CTR-06", not slow, f"median ms: {worst}" + (f"; > 500 ms: {slow}" if slow else ""))

    item = body(create(ta, "dates"))
    ts = item.get("created_at")
    tz = isinstance(ts, str) and (ts.endswith("Z") or ts[-6] in "+-")
    check("CTR-07", tz, f"created_at = {ts!r}",
          "" if tz else "timestamps are returned without a time zone (naive UTC), clients may misinterpret them")


# ───────────────────────── 8. E2E ─────────────────────────

def s_e2e():
    _, ue, te, rc = new_user("e2e")
    s = []
    r = create(te, "E2E", "flow"); s.append(r.status_code); iid = body(r)["id"]
    s.append(int(any(x["id"] == iid for x in body(req("GET", "/items/", headers=bearer(te))))))
    s.append(req("PUT", f"/items/{iid}", json_body={"title": "E2E2", "description": "flow"}, headers=bearer(te)).status_code)
    s.append(int(any(x["title"] == "E2E2" for x in body(req("GET", "/items/", headers=bearer(te))))))
    s.append(req("DELETE", f"/items/{iid}", headers=bearer(te)).status_code)
    s.append(int(any(x["id"] == iid for x in body(req("GET", "/items/", headers=bearer(te))))))
    check("E2E-01", s == [201, 1, 200, 1, 204, 0], f"create, listed, update, updated, delete, listed → {s}")

    iid = body(create(S["ta"], "E2E A"))["id"]
    s = [req("PUT", f"/items/{iid}", json_body={"title": "x", "description": "x"}, headers=bearer(S["tb"])).status_code,
         req("DELETE", f"/items/{iid}", headers=bearer(S["tb"])).status_code]
    ok = s == [403, 403] and any(x["id"] == iid and x["title"] == "E2E A" for x in body(req("GET", "/items/", headers=bearer(S["ta"]))))
    check("E2E-02", ok, f"User B PUT / DELETE → {s}; User A item intact: {ok}")

    _, uf, tf, _ = new_user("e2e3")
    ids = [body(create(tf, f"F{i}"))["id"] for i in range(12)]
    for i in ids[:3]:
        req("DELETE", f"/items/{i}", headers=bearer(tf))
    seen, page = [], 1
    while True:
        b = body(all_items(tf, page=page, limit=10))
        if not b["data"]:
            break
        seen += [x["id"] for x in b["data"]]
        page += 1
    mine_seen = [i for i in seen if i in ids]
    deleted_seen = [i for i in mine_seen if i in ids[:3]]
    check("E2E-03", len(mine_seen) == 9 and not deleted_seen,
          f"user's items across all pages: {len(mine_seen)} (expected 9), deleted ones visible: {len(deleted_seen)}",
          "" if not deleted_seen else "deleted items appear in the paginated list (see PAG-13)")

    _, ug, tg, rcg = new_user("e2e4")
    iid = body(create(tg, "E2E4"))["id"]
    r = req("POST", "/users/refresh", cookie=rcg)
    new_tok = body(r)["access_token"]
    r2 = req("PUT", f"/items/{iid}", json_body={"title": "after refresh", "description": "d"}, headers=bearer(new_tok))
    check("E2E-04", r.status_code == 200 and r2.status_code == 200, f"refresh → {r.status_code}, PUT with new token → {r2.status_code}")


def main():
    if not health_ok():
        sys.exit("The stand is not ready")
    print("CL-02 Items run\n")
    for fn in (s_create, s_my_items, s_pagination, s_update, s_delete, s_access, s_contract, s_e2e):
        print(f"── {fn.__name__}", flush=True)
        section(fn)
    save("CL-02", "CL-02 Items", "Local (Docker), qa/docker-compose.functional.yml")


if __name__ == "__main__":
    main()
