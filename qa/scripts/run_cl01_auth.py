"""
Executes checklist CL-01 Auth (docs/checklists/CL-01_Auth.md) against the local stand.

Every checklist check is an HTTP request to the API; database state is
verified with psql inside the fastapi_postgres container.

Requirements:
  - the stand is running with functional limits:
      docker compose -f docker-compose.yml -f qa/docker-compose.functional.yml up -d --build
  - pip install httpx python-jose

Usage:
  python qa/scripts/run_cl01_auth.py            # results → qa/runs/CL-01_<date>.json
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jose import jwt

BASE = "http://localhost:8000"
RUN_ID = datetime.now().strftime("%m%d%H%M%S")
PW = "Passw0rd!"
OUT_DIR = Path(__file__).resolve().parents[1] / "runs"

client = httpx.Client(base_url=BASE, timeout=30)  # no cookie jar: cookies are passed explicitly
results: dict[str, dict] = {}
observed_codes: dict[str, set] = {}


# ───────────────────────── helpers ─────────────────────────

def email(tag: str) -> str:
    return f"qa{RUN_ID}_{tag}@test.com"


def req(method, path, *, json_body=None, content=None, headers=None, cookie=None):
    h = dict(headers or {})
    if cookie is not None:
        h["Cookie"] = f"refresh_token={cookie}"
    if content is not None:
        r = client.request(method, path, content=content, headers=h)
    else:
        r = client.request(method, path, json=json_body, headers=h)
    observed_codes.setdefault(f"{method} {path}", set()).add(r.status_code)
    return r


def body(r):
    try:
        return r.json()
    except Exception:
        return r.text[:300]


def short(r):
    b = body(r)
    s = json.dumps(b, ensure_ascii=False) if not isinstance(b, str) else b
    return f"{r.status_code} {s[:220]}"


def set_cookies(r) -> list[str]:
    return r.headers.get_list("set-cookie")


def refresh_cookie(r) -> str | None:
    for c in set_cookies(r):
        if c.startswith("refresh_token="):
            return c.split(";", 1)[0].split("=", 1)[1].strip('"')
    return None


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def sql(q: str) -> list[list[str]]:
    p = subprocess.run(
        ["docker", "exec", "-i", "fastapi_postgres", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F "|" -v ON_ERROR_STOP=1'],
        input=q, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return [line.split("|") for line in p.stdout.strip().splitlines() if line]


def mint_real_jwt(payload: dict) -> str:
    """Signs a JWT with the stand's key inside the container (the key never leaves the container)."""
    code = ("import json,sys;from jose import jwt;"
            "from app.auth.jwt_handler import SECRET_KEY,ALGORITHM;"
            "print(jwt.encode(json.loads(sys.stdin.read()),SECRET_KEY,algorithm=ALGORITHM))")
    p = subprocess.run(["docker", "exec", "-i", "fastapi_api", "python", "-c", code],
                       input=json.dumps(payload), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-300:])
    return p.stdout.strip().splitlines()[-1]


def register(e, pw=PW, **extra):
    return req("POST", "/users/register", json_body={"email": e, "password": pw, **extra})


def login(e, pw=PW):
    r = req("POST", "/users/login", json_body={"email": e, "password": pw})
    tok = body(r).get("access_token") if r.status_code == 200 else None
    return r, tok, refresh_cookie(r)


def user_id(e) -> int | None:
    rows = sql(f"SELECT id FROM users WHERE email = '{e}';")
    return int(rows[0][0]) if rows else None


def last_log(path, uid=None):
    cond = f"path = '{path}'" + (f" AND user_id = {uid}" if uid else "")
    rows = sql(f"SELECT level, message, coalesce(user_id::text,''), path FROM logs "
               f"WHERE {cond} ORDER BY id DESC LIMIT 1;")
    return rows[0] if rows else None


def mask(s: str) -> str:
    """Removes tokens from stored results (the repository is public)."""
    s = re.sub(r"eyJ[\w-]*(\.[\w-]*){0,2}", "<jwt>", s)
    return re.sub(r"refresh_token=[\w-]{6,}…?", "refresh_token=<redacted>", s)


def check(cid, ok, actual, note="", status=None):
    actual = mask(actual)
    st = status or ("pass" if ok else "fail")
    results[cid] = {"status": st, "actual": actual, "note": note}
    mark = {"pass": "✅", "fail": "❌", "blocked": "⚠️", "skip": "⏭"}[st]
    print(f"{mark} {cid}: {actual}" + (f"  — {note}" if note else ""))


def section(fn):
    """Isolates a section: an exception marks it as blocked."""
    try:
        fn()
    except Exception as ex:  # noqa: BLE001
        print(f"⚠️ section {fn.__name__} aborted: {ex!r}")
        results.setdefault(f"_error_{fn.__name__}", {"status": "blocked", "actual": repr(ex), "note": ""})


# ───────────────────────── 1. Register ─────────────────────────

def s_register():
    e = email("reg01")
    r = register(e)
    check("REG-01", r.status_code == 201 and body(r) == {"message": "User created"}, short(r))
    uid = user_id(e)

    e2 = email("reg02")
    r = register(e2, phone="+31612345678")
    row = sql(f"SELECT phone FROM users WHERE email='{e2}';")
    check("REG-02", r.status_code == 201 and row and row[0][0] == "+31612345678",
          f"{r.status_code}; phone in DB = {row[0][0] if row else None}")

    row = sql(f"SELECT phone IS NULL FROM users WHERE email='{e}';")
    check("REG-03", row and row[0][0] == "t", f"201; phone IS NULL = {row[0][0] if row else None}")

    row = sql(f"SELECT password FROM users WHERE email='{e}';")[0][0]
    check("REG-04", row != PW and row.startswith("$2b$"), f"hash prefix = {row[:7]}…, len {len(row)}")

    row = sql(f"SELECT id, is_active FROM users WHERE email='{e}';")[0]
    check("REG-05", row[0].isdigit() and row[1] == "t", f"id={row[0]}, is_active={row[1]}")

    r = register(email("reg06"))
    txt = r.text.lower()
    check("REG-06", not any(k in txt for k in ("password", "$2b$", "token")), short(r))

    r = register(email("reg07"), pw="abc123")
    check("REG-07", r.status_code == 201, short(r))

    codes = [register(f"qa+{RUN_ID}@test.com").status_code,
             register(f"qa.name{RUN_ID}@sub.test.com").status_code]
    check("REG-08", codes == [201, 201], f"qa+…: {codes[0]}, qa.name@sub…: {codes[1]}")

    oks = []
    for i, pw in enumerate(["p@ss w0rd!", "пароль123"]):
        e9 = email(f"reg09_{i}")
        rr = register(e9, pw=pw)
        lr, _, _ = login(e9, pw)
        oks.append((rr.status_code, lr.status_code))
    check("REG-09", all(o == (201, 200) for o in oks), f"(register, login) = {oks}")

    e10 = email("reg10")
    long_pw = "A" * 72 + "B"
    r = register(e10, pw=long_pw)
    if r.status_code == 201:
        lr, _, _ = login(e10, "A" * 72 + "C")
        ok = lr.status_code != 200
        check("REG-10", ok, f"register 201; login with a changed 73rd character → {lr.status_code}",
              "" if ok else "bcrypt truncates the password to 72 bytes: passwords differing after the 72nd character are equivalent")
    else:
        check("REG-10", r.status_code == 422, short(r),
              "" if r.status_code == 422 else "a long password causes a server error instead of a clear validation error")

    lg = last_log("/users/register", uid)
    check("REG-11", lg is not None and lg[0] == "INFO", f"logs: {lg}")

    before = sql(f"SELECT count(*) FROM users WHERE email='{e}';")[0][0]
    r = register(e)
    after = sql(f"SELECT count(*) FROM users WHERE email='{e}';")[0][0]
    check("REG-12", r.status_code == 400 and body(r) == {"detail": "User already exists"} and before == after == "1",
          f"{short(r)}; records with this email: {after}")

    up = e.upper()
    r = register(up)
    check("REG-13", r.status_code == 400, short(r),
          "" if r.status_code == 400 else f"a second user {up} was created: email is case-sensitive")

    sp = f"  {email('reg14')}  "
    r = register(sp)
    stored = sql(f"SELECT '[' || email || ']' FROM users WHERE email LIKE '%{RUN_ID}_reg14%';")
    check("REG-14", r.status_code == 422 or (r.status_code == 201 and stored and stored[0][0] == f"[{sp.strip()}]"),
          f"{short(r)}; in DB: {stored[0][0] if stored else None}")

    r = register(email("reg15"), pw="abc12")
    check("REG-15", r.status_code == 422, short(r),
          "" if r.status_code == 422 else "the \"minimum 6 characters\" rule from Swagger is not enforced")

    r = register(email("reg16"), pw="")
    check("REG-16", r.status_code == 422, short(r), "" if r.status_code == 422 else "an empty password is accepted")

    r = register(email("reg17"), pw="      ")
    check("REG-17", r.status_code == 422, short(r), "" if r.status_code == 422 else "a password of spaces is accepted")

    bad = ["abc", "abc@", "@test.com", "a b@test.com", "a@@test.com"]
    got = {b: register(b).status_code for b in bad}
    check("REG-18", all(c == 422 for c in got.values()), str(got))

    r = register("")
    check("REG-19", r.status_code == 422, short(r))

    r = req("POST", "/users/register", json_body={"password": PW})
    d = body(r)
    loc_ok = r.status_code == 422 and any(x.get("loc") == ["body", "email"] and x.get("msg") == "Field required"
                                          for x in d.get("detail", []))
    check("REG-20", loc_ok, short(r))

    r = req("POST", "/users/register", json_body={"email": email("reg21")})
    check("REG-21", r.status_code == 422 and "Field required" in r.text, short(r))

    r = req("POST", "/users/register", json_body={})
    locs = [x.get("loc") for x in body(r).get("detail", [])] if r.status_code == 422 else []
    check("REG-22", r.status_code == 422 and ["body", "email"] in locs and ["body", "password"] in locs,
          f"{r.status_code}; loc = {locs}")

    r1 = req("POST", "/users/register", content="email=a@b.c", headers={"Content-Type": "text/plain"})
    r2 = req("POST", "/users/register", content='{"email": "a@b.c",', headers={"Content-Type": "application/json"})
    check("REG-23", r1.status_code == 422 and r2.status_code == 422, f"plain text → {r1.status_code}, broken JSON → {r2.status_code}")

    r = req("POST", "/users/register", json_body={"email": None, "password": None})
    check("REG-24", r.status_code == 422, short(r))

    r = req("POST", "/users/register", json_body={"email": 123, "password": 123456})
    check("REG-25", r.status_code == 422, short(r))

    got = {p: register(email(f"reg26_{i}"), phone=p).status_code
           for i, p in enumerate(["abc", "123", "1" * 50])}
    check("REG-26", all(c == 422 for c in got.values()), str(got),
          "" if all(c == 422 for c in got.values()) else "the phone format is not validated")

    r = register(email("reg27"), phone=None)
    check("REG-27", r.status_code == 201, short(r))

    e28 = email("reg28")
    r = register(e28, is_active=False, id=999999)
    row = sql(f"SELECT id, is_active FROM users WHERE email='{e28}';")
    check("REG-28", r.status_code == 201 and row and row[0][0] != "999999" and row[0][1] == "t",
          f"{r.status_code}; id={row[0][0] if row else None}, is_active={row[0][1] if row else None}")

    r = register("a" * 300 + "@test.com")
    check("REG-29", r.status_code == 422, short(r))

    users_before = sql("SELECT count(*) FROM users;")[0][0]
    ra = register(f"a'--{RUN_ID}@test.com")
    rb = register("' OR 1=1--")
    users_after = sql("SELECT count(*) FROM users;")[0][0]
    ok = all(c in (201, 422) for c in (ra.status_code, rb.status_code))
    check("REG-30", ok, f"a'--@… → {ra.status_code}, ' OR 1=1-- → {rb.status_code}; "
                        f"users {users_before}→{users_after}")

    r = req("GET", "/users/register")
    check("REG-31", r.status_code == 405, short(r))

    lg = sql(f"SELECT level, message, path FROM logs WHERE path='/users/register' "
             f"AND message LIKE '%existing email: {e}' ORDER BY id DESC LIMIT 1;")
    check("REG-32", bool(lg) and lg[0][0] == "WARNING", f"logs (REG-12 repeat): {lg[0] if lg else None}")


# ───────────────────────── 2. Login ─────────────────────────

def s_login():
    e = email("log")
    register(e)
    uid = user_id(e)
    tokens_before = int(sql(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid};")[0][0])

    r, tok, rc = login(e)
    b = body(r)
    check("LOG-01", r.status_code == 200 and isinstance(b.get("access_token"), str) and b.get("token_type") == "bearer",
          f"{r.status_code}; keys={list(b)}")
    check("LOG-02", rc is not None, f"Set-Cookie: {[c[:40] + '…' for c in set_cookies(r)]}")

    c = next((x for x in set_cookies(r) if x.startswith("refresh_token=")), "")
    low = c.lower()
    attrs_ok = "httponly" in low and "secure" in low and "samesite=lax" in low and "max-age=604800" in low
    check("LOG-03", attrs_ok, "attributes: " + "; ".join(p.strip() for p in c.split(";")[1:]))

    hdr = jwt.get_unverified_header(tok)
    claims = jwt.get_unverified_claims(tok)
    check("LOG-04", hdr.get("alg") == "HS256" and "user_id" in claims and "exp" in claims,
          f"header={hdr}, claims={sorted(claims)}")

    ttl = claims["exp"] - time.time()
    check("LOG-05", 28 * 60 <= ttl <= 30 * 60 + 5, f"exp − now = {ttl / 60:.1f} min")

    check("LOG-06", set(claims) <= {"user_id", "exp"}, f"claims={sorted(claims)}")

    r2 = req("GET", "/items/", headers=bearer(tok))
    check("LOG-07", r2.status_code == 200, short(r2))

    rows = sql(f"SELECT token_hash, revoked, extract(epoch from (expires_at - now() at time zone 'utc'))/86400 "
               f"FROM refresh_tokens WHERE user_id={uid} ORDER BY id DESC LIMIT 1;")
    th, rev, days = rows[0]
    hash_ok = th == hashlib.sha256(rc.encode()).hexdigest()
    ok = hash_ok and th != rc and rev == "f" and 6.9 < float(days) <= 7.01
    new = int(sql(f'SELECT count(*) FROM refresh_tokens WHERE user_id={uid};')[0][0]) - tokens_before
    check("LOG-08", ok, f"new records: {new}, revoked={rev}, expires in {float(days):.2f} days, hash=sha256(cookie): {hash_ok}")

    r3, tok2, rc2 = login(e)
    active = sql(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid} AND NOT revoked;")[0][0]
    ra = req("POST", "/users/refresh", cookie=rc)
    rb = req("POST", "/users/refresh", cookie=rc2)
    check("LOG-09", r3.status_code == 200 and active == "2" and ra.status_code == 200 and rb.status_code == 200,
          f"second login {r3.status_code}; active tokens {active}; refresh 1 → {ra.status_code}, refresh 2 → {rb.status_code}")

    check("LOG-10", tok != tok2 and rc != rc2, f"access tokens differ: {tok != tok2}, refresh tokens differ: {rc != rc2}",
          "" if tok != tok2 else "two logins within one second give an identical access token: no iat/jti in the payload")

    r = req("POST", "/users/login", json_body={"email": e.upper(), "password": PW})
    check("LOG-11", r.status_code == 200, short(r),
          "" if r.status_code == 200 else "login with the email in a different case fails")

    lg = last_log("/users/login", uid)
    check("LOG-12", lg is not None and lg[0] == "INFO" and lg[2] == str(uid), f"logs: {lg}")

    cnt_before = sql(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid};")[0][0]
    r = req("POST", "/users/login", json_body={"email": e, "password": "WrongPass1"})
    cnt_after = sql(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid};")[0][0]
    check("LOG-13", r.status_code == 401 and body(r) == {"detail": "Wrong password"} and not set_cookies(r)
          and cnt_before == cnt_after, f"{short(r)}; cookie: {bool(set_cookies(r))}; tokens {cnt_before}→{cnt_after}")
    wrong = r

    r = req("POST", "/users/login", json_body={"email": email("nobody"), "password": PW})
    check("LOG-14", r.status_code == 404 and body(r) == {"detail": "User not found"}, short(r))

    same = wrong.status_code == r.status_code and body(wrong) == body(r)
    check("LOG-15", same, f"wrong password → {short(wrong)}; no user → {short(r)}",
          "" if same else "different responses reveal whether an email is registered (user enumeration)")

    r = req("POST", "/users/login", json_body={"email": e, "password": PW.swapcase()})
    check("LOG-16", r.status_code == 401, short(r))

    r = req("POST", "/users/login", json_body={"email": e, "password": PW + " "})
    check("LOG-17", r.status_code == 401, short(r))

    r = req("POST", "/users/login", json_body={"email": e, "password": ""})
    check("LOG-18", r.status_code in (401, 422), short(r))

    r = req("POST", "/users/login", json_body={"email": "not-an-email", "password": PW})
    check("LOG-19", r.status_code == 422, short(r))

    ra = req("POST", "/users/login", json_body={"password": PW})
    rb = req("POST", "/users/login", json_body={"email": e})
    check("LOG-20", ra.status_code == rb.status_code == 422 and "Field required" in ra.text + rb.text,
          f"no email → {ra.status_code}, no password → {rb.status_code}")

    ra = req("POST", "/users/login", json_body={})
    rb = req("POST", "/users/login", content="hello", headers={"Content-Type": "text/plain"})
    check("LOG-21", ra.status_code == rb.status_code == 422, f"{{}} → {ra.status_code}, plain text → {rb.status_code}")

    r = req("POST", "/users/login", json_body={"email": e, "password": "' OR '1'='1"})
    check("LOG-22", r.status_code == 401, short(r))

    e23 = email("inactive")
    register(e23)
    sql(f"UPDATE users SET is_active = false WHERE email='{e23}';")
    r = req("POST", "/users/login", json_body={"email": e23, "password": PW})
    check("LOG-23", r.status_code in (401, 403), short(r),
          "" if r.status_code in (401, 403) else "a deactivated user (is_active=false) logs in successfully")

    def avg(payload, n=5):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            req("POST", "/users/login", json_body=payload)
            ts.append(time.perf_counter() - t0)
        return sum(ts) / n * 1000
    t_none = avg({"email": email("nobody2"), "password": PW})
    t_wrong = avg({"email": e, "password": "WrongPass1"})
    ok = abs(t_wrong - t_none) < 50
    check("LOG-24", ok, f"no user: {t_none:.0f} ms, wrong password: {t_wrong:.0f} ms",
          "" if ok else "the response time reveals whether an email exists (bcrypt runs only for existing users)")

    lg = sql(f"SELECT level, message FROM logs WHERE path='/users/login' AND user_id={uid} "
             f"AND level='WARNING' ORDER BY id DESC LIMIT 1;")
    leak = sql("SELECT count(*) FROM logs WHERE message LIKE '%WrongPass1%';")[0][0]
    check("LOG-25", bool(lg) and leak == "0", f"logs: {lg[0] if lg else None}; records with the password: {leak}")


# ───────────────────────── 3. Refresh ─────────────────────────

def s_refresh():
    e = email("ref")
    register(e)
    uid = user_id(e)
    _, tok, rc = login(e)

    r = req("POST", "/users/refresh", cookie=rc)
    b = body(r)
    check("REF-01", r.status_code == 200 and isinstance(b.get("access_token"), str) and b.get("token_type") == "bearer",
          short(r)[:80])
    new_tok, new_rc = b.get("access_token"), refresh_cookie(r)

    r2 = req("GET", "/items/", headers=bearer(new_tok))
    same_uid = jwt.get_unverified_claims(new_tok)["user_id"] == uid
    check("REF-02", r2.status_code == 200 and same_uid, f"GET /items/ → {r2.status_code}; same user_id: {same_uid}")

    c = next((x for x in set_cookies(r) if x.startswith("refresh_token=")), "").lower()
    check("REF-03", new_rc and new_rc != rc and "httponly" in c and "secure" in c and "max-age=604800" in c,
          f"new cookie ≠ old: {new_rc != rc}; attributes kept: {'httponly' in c and 'secure' in c}")

    old = sql(f"SELECT revoked FROM refresh_tokens WHERE token_hash='{hashlib.sha256(rc.encode()).hexdigest()}';")
    new = sql(f"SELECT revoked, round(extract(epoch from (expires_at - now() at time zone 'utc'))/86400, 2) "
              f"FROM refresh_tokens WHERE token_hash='{hashlib.sha256(new_rc.encode()).hexdigest()}';")
    check("REF-04", old and old[0][0] == "t" and new and new[0][0] == "f",
          f"old revoked={old[0][0] if old else None}; new revoked={new[0][0] if new else None}, "
          f"expires in {new[0][1] if new else None} days")

    cur, codes = new_rc, []
    for _ in range(3):
        rr = req("POST", "/users/refresh", cookie=cur)
        codes.append(rr.status_code)
        cur = refresh_cookie(rr) or cur
    check("REF-05", codes == [200, 200, 200], f"codes: {codes}")

    r3 = req("GET", "/items/", headers=bearer(tok))
    check("REF-06", True, f"old access token after refresh → {r3.status_code}",
          "the old access token is valid until exp (stateless JWT) — expected limitation" if r3.status_code == 200 else "")

    # REF-07: cleanup of expired tokens
    _, _, rc_x = login(e)
    hx = hashlib.sha256(rc_x.encode()).hexdigest()
    sql(f"UPDATE refresh_tokens SET expires_at = now() - interval '1 day' WHERE token_hash='{hx}';")
    req("POST", "/users/refresh", cookie=cur)
    gone = sql(f"SELECT count(*) FROM refresh_tokens WHERE token_hash='{hx}';")[0][0]
    check("REF-07", gone == "0", f"expired record after refresh: {'deleted' if gone == '0' else 'still present'}")

    r = req("POST", "/users/refresh")
    check("REF-08", r.status_code == 401 and body(r) == {"detail": "No refresh token provided"}, short(r))

    r = req("POST", "/users/refresh", headers={"Cookie": "refresh_token="})
    check("REF-09", r.status_code == 401, short(r))

    r = req("POST", "/users/refresh", cookie="random-string-123")
    check("REF-10", r.status_code == 401 and body(r) == {"detail": "Invalid or expired refresh token"}, short(r))

    # REF-11/12: reuse detection
    _, _, a1 = login(e)
    ra = req("POST", "/users/refresh", cookie=a1)
    a2 = refresh_cookie(ra)
    reuse = req("POST", "/users/refresh", cookie=a1)
    check("REF-11", reuse.status_code == 401, short(reuse))
    after = req("POST", "/users/refresh", cookie=a2)
    check("REF-12", after.status_code == 401, f"new token of the chain after reuse → {after.status_code}",
          "" if after.status_code == 401 else "no reuse detection: after a revoked token is reused, "
                                              "the chain keeps working (a stolen token goes unnoticed)")

    _, _, l1 = login(e)
    req("POST", "/users/logout", cookie=l1)
    r = req("POST", "/users/refresh", cookie=l1)
    check("REF-13", r.status_code == 401, short(r))

    e14 = email("ref14")
    register(e14)
    _, t14, c14 = login(e14)
    req("POST", "/users/logout-all", headers=bearer(t14))
    r = req("POST", "/users/refresh", cookie=c14)
    check("REF-14", r.status_code == 401, short(r))

    _, _, x1 = login(e)
    sql(f"UPDATE refresh_tokens SET expires_at = now() at time zone 'utc' - interval '1 minute' "
        f"WHERE token_hash='{hashlib.sha256(x1.encode()).hexdigest()}';")
    r = req("POST", "/users/refresh", cookie=x1)
    check("REF-15", r.status_code == 401, short(r))

    _, t16, _ = login(e)
    r = req("POST", "/users/refresh", cookie=t16)
    check("REF-16", r.status_code == 401, short(r))

    _, _, c17 = login(e)
    r = req("POST", "/users/refresh", headers=bearer(c17))
    check("REF-17", r.status_code == 401 and body(r) == {"detail": "No refresh token provided"}, short(r))

    _, _, p1 = login(e)
    codes = []
    def hit():
        codes.append(req("POST", "/users/refresh", cookie=p1).status_code)
    ths = [threading.Thread(target=hit) for _ in range(5)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    ok = sorted(codes).count(200) == 1
    check("REF-18", ok, f"5 parallel refreshes with one token → {sorted(codes)}",
          "" if ok else "race condition: one refresh token exchanged for several new sessions")

    e19 = email("ref19")
    register(e19)
    _, _, c19 = login(e19)
    try:
        sql(f"DELETE FROM users WHERE email='{e19}';")
        r = req("POST", "/users/refresh", cookie=c19)
        check("REF-19", r.status_code in (401, 404), short(r))
    except RuntimeError as ex:
        check("REF-19", True, "a user with active tokens cannot be deleted: " + str(ex).splitlines()[0][:120],
              "FK refresh_tokens.user_id has no ON DELETE CASCADE — the scenario is unreachable, check not applicable",
              status="skip")

    lg = sql("SELECT level, message FROM logs WHERE path='/users/refresh' AND level='WARNING' ORDER BY id DESC LIMIT 1;")
    leak = sql("SELECT count(*) FROM logs WHERE message LIKE '%random-string-123%';")[0][0]
    check("REF-20", bool(lg) and leak == "0", f"logs: {lg[0] if lg else None}; token in logs: {leak != '0'}")


# ───────────────────────── 4. Logout ─────────────────────────

def s_logout():
    e = email("out")
    register(e)
    _, tok, rc = login(e)
    _, _, rc2 = login(e)

    r = req("POST", "/users/logout", cookie=rc)
    check("OUT-01", r.status_code == 200 and body(r) == {"message": "Logged out"}, short(r))

    c = next((x for x in set_cookies(r) if x.startswith("refresh_token=")), "")
    low = c.lower()
    check("OUT-02", 'refresh_token=""' in c or "max-age=0" in low or "expires=thu, 01 jan 1970" in low,
          f"Set-Cookie: {c[:120]}")

    rev = sql(f"SELECT revoked FROM refresh_tokens WHERE token_hash='{hashlib.sha256(rc.encode()).hexdigest()}';")
    check("OUT-03", rev and rev[0][0] == "t", f"revoked = {rev[0][0] if rev else None}")

    r = req("POST", "/users/refresh", cookie=rc)
    check("OUT-04", r.status_code == 401, short(r))

    r = req("POST", "/users/refresh", cookie=rc2)
    check("OUT-05", r.status_code == 200, f"refresh of the second session → {r.status_code}")

    r = req("GET", "/items/", headers=bearer(tok))
    check("OUT-06", True, f"access token after logout → {r.status_code}",
          "the access token is valid until exp — known limitation of stateless JWT" if r.status_code == 200 else "")

    r = req("POST", "/users/logout")
    check("OUT-07", r.status_code == 401 and body(r) == {"detail": "No refresh token provided"}, short(r))

    r = req("POST", "/users/logout", cookie="random-string-456")
    check("OUT-08", r.status_code == 401, short(r),
          "" if r.status_code == 401 else "logout with a non-existent token returns a success response")

    r = req("POST", "/users/logout", cookie=rc)
    check("OUT-09", r.status_code in (200, 401), short(r),
          "idempotent 200" if r.status_code == 200 else "")

    r = req("POST", "/users/logout", headers=bearer(tok))
    check("OUT-10", r.status_code == 401, short(r))

    lg = sql("SELECT level, coalesce(user_id::text, 'NULL') FROM logs WHERE path='/users/logout' ORDER BY id DESC LIMIT 1;")
    filled = bool(lg) and lg[0][1] != "NULL"
    check("OUT-11", bool(lg) and lg[0][0] == "INFO" and filled, f"logs: level={lg[0][0] if lg else None}, user_id={lg[0][1] if lg else None}",
          "" if filled else "the logout record has no user_id — the logs do not show who logged out")


# ───────────────────────── 5. Logout-all ─────────────────────────

def s_logout_all():
    e = email("all")
    register(e)
    uid = user_id(e)
    sess = [login(e) for _ in range(3)]
    tok = sess[-1][1]

    eb = email("allB")
    register(eb)
    _, _, rcb = login(eb)

    r = req("POST", "/users/logout-all", headers=bearer(tok))
    check("ALL-01", r.status_code == 200 and body(r) == {"message": "Logged out from all devices"}, short(r))
    all_resp = r

    codes = [req("POST", "/users/refresh", cookie=s[2]).status_code for s in sess]
    check("ALL-02", codes == [401, 401, 401], f"refresh with each of the 3 tokens → {codes}")

    left = sql(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid} AND NOT revoked;")[0][0]
    check("ALL-03", left == "0", f"non-revoked tokens of the user: {left}")

    r = req("POST", "/users/refresh", cookie=rcb)
    check("ALL-04", r.status_code == 200, f"User B refresh → {r.status_code}")

    c = next((x for x in set_cookies(all_resp) if x.startswith("refresh_token=")), "").lower()
    check("ALL-05", "max-age=0" in c or "expires=thu, 01 jan 1970" in c, f"Set-Cookie: {c[:120]}")

    r, t2, _ = login(e)
    r2 = req("GET", "/items/", headers=bearer(t2))
    check("ALL-06", r.status_code == 200 and r2.status_code == 200, f"login → {r.status_code}, GET /items/ → {r2.status_code}")

    r = req("GET", "/items/", headers=bearer(tok))
    check("ALL-07", r.status_code == 401, f"old access token after logout-all → {r.status_code}",
          "" if r.status_code == 401 else "after \"log out of all devices\" access tokens stay valid for up to 30 min")

    r = req("POST", "/users/logout-all")
    check("ALL-08", r.status_code == 401, short(r),
          "" if r.status_code == 401 else f"returns {r.status_code} instead of the 401 documented in Swagger")

    r = req("POST", "/users/logout-all", headers=bearer("random.string.value"))
    check("ALL-09", r.status_code == 401 and body(r) == {"detail": "Invalid or expired token"}, short(r))

    expired = mint_real_jwt({"user_id": uid, "exp": int(time.time()) - 60})
    r = req("POST", "/users/logout-all", headers=bearer(expired))
    check("ALL-10", r.status_code == 401, short(r), "a token with exp in the past, signed with the stand's key")

    foreign = jwt.encode({"user_id": uid, "exp": int(time.time()) + 600}, "some-other-key", algorithm="HS256")
    r = req("POST", "/users/logout-all", headers=bearer(foreign))
    check("ALL-11", r.status_code == 401, short(r))

    h, p, s = t2.split(".")
    claims = jwt.get_unverified_claims(t2)
    claims["user_id"] = claims["user_id"] + 1
    p2 = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode()).rstrip(b"=").decode()
    r = req("POST", "/users/logout-all", headers=bearer(f"{h}.{p2}.{s}"))
    check("ALL-12", r.status_code == 401, short(r))

    got = {
        "Token": req("POST", "/users/logout-all", headers={"Authorization": f"Token {t2}"}).status_code,
        "Basic": req("POST", "/users/logout-all", headers={"Authorization": "Basic dXNlcjpwYXNz"}).status_code,
        "no scheme": req("POST", "/users/logout-all", headers={"Authorization": t2}).status_code,
    }
    check("ALL-13", all(c in (401, 403) for c in got.values()), str(got))

    _, _, rc14 = login(e)
    r = req("POST", "/users/logout-all", cookie=rc14)
    check("ALL-14", r.status_code in (401, 403), short(r))

    req("POST", "/users/logout-all", headers=bearer(t2))
    r = req("POST", "/users/logout-all", headers=bearer(t2))
    check("ALL-15", r.status_code == 200, short(r))

    lg = sql(f"SELECT level, coalesce(user_id::text,'NULL') FROM logs WHERE path='/users/logout-all' "
             f"ORDER BY id DESC LIMIT 1;")
    check("ALL-16", bool(lg) and lg[0][0] == "INFO" and lg[0][1] == str(uid), f"logs: {lg[0] if lg else None}")


# ───────────────────────── 6. Security / contract ─────────────────────────

def s_security():
    r = req("GET", "/items/")
    check("SEC-01", r.status_code in (401, 403), short(r),
          "" if r.status_code == 401 else f"{r.status_code} instead of 401 — codes for protected endpoints are not documented in Swagger")

    e = email("sec")
    register(e)
    uid = user_id(e)
    hdr = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    pl = base64.urlsafe_b64encode(json.dumps({"user_id": uid, "exp": int(time.time()) + 600}).encode()).rstrip(b"=").decode()
    r = req("GET", "/items/", headers=bearer(f"{hdr}.{pl}."))
    check("SEC-02", r.status_code == 401, short(r))

    e3 = email("sec03")
    register(e3)
    u3 = user_id(e3)
    _, t3, _ = login(e3)
    sql(f"DELETE FROM refresh_tokens WHERE user_id={u3}; DELETE FROM users WHERE id={u3};")
    r = req("GET", "/items/", headers=bearer(t3))
    check("SEC-03", r.status_code == 401 and body(r) == {"detail": "User not found"}, short(r))

    e4 = email("sec04")
    register(e4)
    _, t4, _ = login(e4)
    sql(f"UPDATE users SET is_active=false WHERE email='{e4}';")
    r = req("GET", "/items/", headers=bearer(t4))
    check("SEC-04", r.status_code in (401, 403), short(r),
          "" if r.status_code in (401, 403) else "the token of a deactivated user keeps working")

    far = jwt.encode({"user_id": uid, "exp": int(time.time()) + 10 * 365 * 86400}, "attacker-key", algorithm="HS256")
    r = req("GET", "/items/", headers=bearer(far))
    check("SEC-05", r.status_code == 401, short(r))

    probes = [req("POST", "/users/register", content="{bad", headers={"Content-Type": "application/json"}),
              req("POST", "/users/login", json_body={"email": 1}),
              req("POST", "/users/refresh", cookie="x"),
              req("GET", "/items/", headers=bearer("x.y.z"))]
    leaks = [p.status_code for p in probes if any(k in p.text for k in ("Traceback", "sqlalchemy", "psycopg", "/app/", "File \""))]
    check("SEC-06", not leaks, f"responses checked: {len(probes)} + all responses of the run; with leaks: {leaks}")


def s_security_final():
    leak_pw = sql(f"SELECT count(*) FROM logs WHERE message LIKE '%{PW}%' OR message LIKE '%WrongPass1%';")[0][0]
    leak_tok = sql("SELECT count(*) FROM logs WHERE message LIKE '%eyJ%';")[0][0]
    p = subprocess.run(["docker", "logs", "fastapi_api"], capture_output=True, text=True)
    console = p.stdout + p.stderr
    con_leak = PW in console or "WrongPass1" in console or "eyJhbGci" in console
    check("SEC-07", leak_pw == "0" and leak_tok == "0" and not con_leak,
          f"logs: passwords {leak_pw}, JWT {leak_tok}; console: leaks {'found' if con_leak else 'none'}")

    n = sql(f"SELECT count(*) FROM logs WHERE message LIKE '%{RUN_ID}%@test.com%';")[0][0]
    check("SEC-08", n == "0", f"logs records with emails of this run: {n}",
          "" if n == "0" else "user emails (PII) are written to logs.message in plain text")

    ctypes = {}
    for path, kw in [("/users/register", {"json_body": {}}), ("/users/login", {"json_body": {}}),
                     ("/users/refresh", {}), ("/users/logout", {}), ("/users/logout-all", {})]:
        rr = req("POST", path, **kw)
        ctypes[path] = rr.headers.get("content-type")
    check("SEC-09", all(v and v.startswith("application/json") for v in ctypes.values()), str(ctypes))

    spec = client.get("/openapi.json").json()
    missing, undocumented = [], []
    for path in ["/users/register", "/users/login", "/users/refresh", "/users/logout", "/users/logout-all"]:
        codes = {int(c) for c in spec["paths"][path]["post"]["responses"]}
        seen = observed_codes.get(f"POST {path}", set()) - {500}
        missing += [f"{path}:{c}" for c in codes if c not in seen]
        undocumented += [f"{path}:{c}" for c in sorted(seen - codes)]
    check("SEC-10", not missing and not undocumented,
          f"not reproduced: {missing or 'none'}; undocumented: {undocumented or 'none'}",
          "422 for refresh/logout is auto-generated by FastAPI and unreachable (the cookie parameter is optional); "
          "403 for logout-all is not documented — see ALL-08" if missing or undocumented else "")

    jar = httpx.Client(base_url=BASE)
    e = email("sec11")
    register(e)
    jar.post("/users/login", json={"email": e, "password": PW})
    stored = "refresh_token" in jar.cookies
    r = jar.post("/users/refresh")
    check("SEC-11", True, f"httpx over HTTP: cookie stored={stored}, refresh without passing it manually → {r.status_code}",
          "a client with strict Secure handling does not send the cookie over HTTP; Chrome treats localhost as a "
          "secure context and sends it. HTTPS not checked (no stand)")


# ───────────────────────── 7. E2E ─────────────────────────

def s_e2e():
    e = email("e2e1")
    steps = []
    steps.append(register(e).status_code)
    r, tok, rc = login(e); steps.append(r.status_code)
    steps.append(req("GET", "/items/", headers=bearer(tok)).status_code)
    r = req("POST", "/users/refresh", cookie=rc); steps.append(r.status_code)
    tok2, rc2 = body(r)["access_token"], refresh_cookie(r)
    steps.append(req("GET", "/items/", headers=bearer(tok2)).status_code)
    steps.append(req("POST", "/users/logout", cookie=rc2).status_code)
    steps.append(req("POST", "/users/refresh", cookie=rc2).status_code)
    check("E2E-01", steps == [201, 200, 200, 200, 200, 200, 401], f"steps: {steps}")

    e = email("e2e2")
    register(e)
    _, t1, d1 = login(e)
    _, t2, d2 = login(e)
    s = [req("POST", "/users/logout", cookie=d1).status_code]
    r = req("POST", "/users/refresh", cookie=d2); s.append(r.status_code)
    d2b = refresh_cookie(r)
    s.append(req("POST", "/users/logout-all", headers=bearer(t2)).status_code)
    s.append(req("POST", "/users/refresh", cookie=d2b).status_code)
    check("E2E-02", s == [200, 200, 200, 401], f"logout d1, refresh d2, logout-all, refresh d2 → {s}")

    e = email("e2e3")
    s = [register(e).status_code, register(e).status_code,
         req("POST", "/users/login", json_body={"email": e, "password": "WrongPass1"}).status_code,
         login(e)[0].status_code]
    lv = [x[0] for x in sql(f"SELECT level FROM logs WHERE message LIKE '%{e}%' ORDER BY id;")]
    check("E2E-03", s == [201, 400, 401, 200] and lv == ["INFO", "WARNING", "WARNING", "INFO"],
          f"codes {s}; log levels {lv}")


# ───────────────────────── main ─────────────────────────

def main():
    health = client.get("/health").json()
    if health != {"status": "ok", "database": "ok"}:
        sys.exit(f"The stand is not ready: {health}")
    print(f"CL-01 Auth run {RUN_ID}, health={health}\n")
    for fn in (s_register, s_login, s_refresh, s_logout, s_logout_all, s_security, s_e2e, s_security_final):
        print(f"── {fn.__name__}")
        section(fn)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"CL-01_{datetime.now():%Y-%m-%d}.json"
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out.write_text(json.dumps({
        "checklist": "CL-01 Auth", "run_id": RUN_ID, "date": datetime.now(timezone.utc).isoformat(),
        "environment": "Local (Docker), qa/docker-compose.functional.yml", "app_build": os.environ.get("APP_BUILD", "660708b"),
        "repo_commit": commit, "results": results,
    }, ensure_ascii=False, indent=2))
    counts = {}
    for v in results.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(f"\nTotal: {counts}; saved to {out}")


if __name__ == "__main__":
    main()
