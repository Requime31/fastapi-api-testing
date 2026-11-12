"""
Cycle 2 re-test: verifies the fixes for FAT-8, FAT-9, FAT-13, FAT-15, FAT-19
on build v1.7.1 by repeating the steps from each bug report, plus a few checks
around each fix (boundaries, legacy data, neighbouring cases).

Check IDs: RT-<bug>-<n>. Results: qa/runs/RETEST-cycle2_<date>.json

Usage: APP_BUILD=v1.7.1 python qa/scripts/retest_cycle2.py
Stand: docker compose -f docker-compose.yml -f qa/docker-compose.functional.yml up -d
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import (APP_BUILD, bearer, body, check, email, login,  # noqa: E402
                    register, req, save, section, short, sql, sql1)


def loc_is_password(r):
    b = body(r)
    return isinstance(b, dict) and any(e.get("loc") == ["body", "password"] for e in b.get("detail", []))


def fat8():
    """FAT-8: password validation on registration (REG-15, REG-16, REG-17)."""
    for n, (tag, pw) in enumerate([("short", "abc12"), ("empty", ""), ("spaces", "      ")], start=1):
        r = register(email(f"fat8_{tag}"), pw)
        e = email(f"fat8_{tag}")
        created = sql1(f"SELECT count(*) FROM users WHERE lower(email) = lower('{e}');")
        check(f"RT-8-{n}", r.status_code == 422 and loc_is_password(r) and created == "0",
              f"password {pw!r} → {short(r, 160)}; user created: {created != '0'}")
    # step 4 of the report: the empty-password account cannot be created, so login is impossible
    r, tok, _ = login(email("fat8_empty"), "")
    check("RT-8-4", r.status_code != 200 and tok is None, f"login with an empty password → {r.status_code}")
    r = register(email("fat8_boundary"), "abc123")
    check("RT-8-5", r.status_code == 201, f"boundary: 6 characters 'abc123' → {short(r)}")
    r = register(email("fat8_padded"), " abc1 ")
    check("RT-8-6", r.status_code == 201, f"6 characters with spaces inside the value ' abc1 ' → {short(r)}",
          "non-blank value of the minimum length is accepted")
    r, tok, _ = login(email("fat8_boundary"), "abc123")
    check("RT-8-7", r.status_code == 200 and tok is not None, f"login with the boundary password → {r.status_code}")


def fat9():
    """FAT-9: case-insensitive email (REG-13, LOG-11)."""
    lower = email("fat9_case")
    upper = lower.upper()
    r = register(lower)
    check("RT-9-1", r.status_code == 201, f"register {lower!r} → {short(r)}")
    r, tok, _ = login(upper)
    check("RT-9-2", r.status_code == 200 and tok is not None, f"login as {upper!r} → {short(r, 80)}")
    r = register(upper)
    n = sql1(f"SELECT count(*) FROM users WHERE lower(email)='{lower}';")
    check("RT-9-3", r.status_code == 400 and n == "1", f"register {upper!r} → {short(r)}; accounts with this address: {n}")
    mixed = email("fat9_Mixed").replace("qa", "QA", 1)
    r = register(mixed)
    stored = sql1(f"SELECT email FROM users WHERE lower(email)='{mixed.lower()}';")
    check("RT-9-4", r.status_code == 201 and stored == mixed.lower(),
          f"register {mixed!r} → {r.status_code}; stored as {stored!r}")
    # legacy data: duplicates created in cycle 1 before the fix
    dups = sql("SELECT lower(email), count(*) FROM users GROUP BY lower(email) HAVING count(*) > 1;")
    check("RT-9-5", True, f"legacy case-duplicates in the database: {len(dups)} address(es)",
          "created before the fix (cycle 1); not removed by the fix — see PR #52 'Known limitation'",
          status="pass")
    # every legacy account must stay reachable: log in with each account's exact email
    # and compare the user_id in the issued token with the account's own id
    rows = sql("SELECT id, email FROM users WHERE lower(email) IN "
               "(SELECT lower(email) FROM users GROUP BY 1 HAVING count(*) > 1) ORDER BY lower(email), id;")
    unreachable = []
    for uid, e in rows:
        r, tok, _ = login(e)
        got = jwt_user_id(tok) if tok else None
        if got != int(uid):
            unreachable.append(f"{uid} ({e.split('@')[0][-5:]}…) → token user_id {got}")
    check("RT-9-6", not unreachable,
          f"legacy duplicate accounts: {len(rows)}; unreachable by their own email: {len(unreachable)}"
          + (f" — {'; '.join(unreachable)}" if unreachable else ""),
          "login by the exact email of an account created before the fix must reach that account")


def jwt_user_id(token):
    import base64, json
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["user_id"]


def fat13():
    """FAT-13: missing credentials → 401 with WWW-Authenticate (ALL-08, SEC-01, SEC-10)."""
    r = req("POST", "/users/logout-all")
    check("RT-13-1", r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer",
          f"POST /users/logout-all without Authorization → {short(r)}; WWW-Authenticate={r.headers.get('www-authenticate')}")
    r = req("GET", "/items/")
    check("RT-13-2", r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer",
          f"GET /items/ without Authorization → {short(r)}; WWW-Authenticate={r.headers.get('www-authenticate')}")
    r = req("GET", "/items/", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    check("RT-13-3", r.status_code == 401, f"Basic scheme → {short(r)}")
    r = req("GET", "/items/", headers={"Authorization": "Bearer"})
    check("RT-13-4", r.status_code == 401, f"'Bearer' without a token → {short(r)}")
    r = req("GET", "/items/", headers=bearer("invalid"))
    check("RT-13-5", r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer",
          f"invalid token → {short(r)}; WWW-Authenticate={r.headers.get('www-authenticate')}")
    spec = req("GET", "/openapi.json").json()
    schemes = list(spec.get("components", {}).get("securitySchemes", {}))
    secured = [f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m, op in ops.items() if op.get("security")]
    check("RT-13-6", "HTTPBearer" in schemes and len(secured) >= 6,
          f"OpenAPI security schemes: {schemes}; secured operations: {len(secured)}",
          "the Authorize button in Swagger keeps working")
    # ownership errors stay 403 — the fix must not change authorisation
    e1 = email("fat13_a"); register(e1); _, t1, _ = login(e1)
    e2 = email("fat13_b"); register(e2); _, t2, _ = login(e2)
    item = req("POST", "/items/", json_body={"title": "t", "description": "d"}, headers=bearer(t1)).json()
    r = req("DELETE", f"/items/{item['id']}", headers=bearer(t2))
    check("RT-13-7", r.status_code == 403, f"someone else's item with a valid token → {short(r)}",
          "authorisation (ownership) still answers 403")


def fat15():
    """FAT-15: phone: null is accepted (REG-27)."""
    e = email("fat15_null")
    r = register(e, phone=None)
    phone = sql1(f"SELECT coalesce(phone, '<NULL>') FROM users WHERE lower(email) = lower('{e}');")
    check("RT-15-1", r.status_code == 201 and phone == "<NULL>", f"phone: null → {short(r)}; phone in DB = {phone}")
    e = email("fat15_value")
    r = register(e, phone="+31612345678")
    phone = sql1(f"SELECT phone FROM users WHERE lower(email) = lower('{e}');")
    check("RT-15-2", r.status_code == 201 and phone == "+31612345678", f"phone value → {r.status_code}; DB = {phone}")
    r = register(email("fat15_number"), phone=12345)
    check("RT-15-3", r.status_code == 422, f"phone as a number → {short(r, 120)}", "type validation is kept")


def fat19():
    """FAT-19: logout log record has user_id (OUT-11)."""
    e = email("fat19")
    register(e)
    _, _, rc = login(e)
    uid = sql1(f"SELECT id FROM users WHERE lower(email) = lower('{e}');")
    r = req("POST", "/users/logout", cookie=rc)
    row = sql("SELECT level, message, coalesce(user_id::text, 'NULL') FROM logs WHERE path='/users/logout' ORDER BY id DESC LIMIT 1;")
    check("RT-19-1", r.status_code == 200 and row and row[0][2] == uid,
          f"logout → {r.status_code}; last log record: {' | '.join(row[0]) if row else None}; user_id expected {uid}")
    r = req("POST", "/users/logout", cookie="not-a-real-token")
    row = sql("SELECT coalesce(user_id::text, 'NULL') FROM logs WHERE path='/users/logout' ORDER BY id DESC LIMIT 1;")
    check("RT-19-2", row and row[0][0] == "NULL", f"logout with an unknown token → {r.status_code}; user_id = {row[0][0] if row else None}",
          "no owner to log; 200 for an unknown token is the separate open defect FAT-14")


if __name__ == "__main__":
    print(f"Re-test, build {APP_BUILD}\n")
    for fn in (fat8, fat9, fat13, fat15, fat19):
        print(f"--- {fn.__doc__.strip()}")
        section(fn)
    save("RETEST-cycle2", "Cycle 2 re-test: FAT-8, FAT-9, FAT-13, FAT-15, FAT-19",
         "Local (Docker), qa/docker-compose.functional.yml")
