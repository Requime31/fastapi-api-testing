"""
Executes checklist CL-03 Rate Limiting (docs/checklists/CL-03_RateLimit.md) against the local stand.

The stand must run WITHOUT the functional override (default limits from .env):
    docker compose -f docker-compose.yml up -d
Counters are reset between checks by restarting the API container. Readiness is polled
from inside the container (client IP 127.0.0.1), so it does not consume the host's limits.
Sections 3 and 7 wait for the 60 s window: the whole run takes ~10 minutes.

Usage: python qa/scripts/run_cl03_rate_limit.py     # results → qa/runs/CL-03_<date>.json
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import OUT_DIR, RUN_ID, results, body, bearer, check, client, email, login, refresh_cookie, register, req, save, section, short, sql, sql1

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
WRONG = {"password": "WrongPass1"}


def in_container(path, method="GET", headers=None):
    """HTTP request from inside the api container (client IP 127.0.0.1 — a separate limit key)."""
    code = ("import sys,urllib.request,json;h=json.loads(sys.argv[3]);"
            "r=urllib.request.Request('http://localhost:8000'+sys.argv[1],method=sys.argv[2],headers=h,"
            "data=(sys.argv[4].encode() if len(sys.argv)>4 else None))\n"
            "try:\n print(urllib.request.urlopen(r,timeout=5).status)\n"
            "except urllib.error.HTTPError as e:\n print(e.code)\n"
            "except Exception:\n print(0)")
    import json as _j
    args = ["docker", "exec", "fastapi_api", "python", "-c", code, path, method, _j.dumps(headers or {})]
    return int(subprocess.run(args, capture_output=True, text=True).stdout.strip() or 0)


def in_container_login(e, pw):
    import json as _j
    code = ("import sys,urllib.request\n"
            "r=urllib.request.Request('http://localhost:8000/users/login',method='POST',"
            "headers={'Content-Type':'application/json'},data=sys.argv[1].encode())\n"
            "try:\n print(urllib.request.urlopen(r,timeout=5).status)\n"
            "except urllib.error.HTTPError as e:\n print(e.code)")
    p = subprocess.run(["docker", "exec", "fastapi_api", "python", "-c", code, _j.dumps({"email": e, "password": pw})],
                       capture_output=True, text=True)
    return int(p.stdout.strip() or 0)


def wait_ready(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if in_container("/health") == 200:
            return True
        time.sleep(0.5)
    raise RuntimeError("API did not become ready")


def reset():
    subprocess.run(["docker", "restart", "fastapi_api"], capture_output=True, check=True)
    time.sleep(1)
    wait_ready()


def compose_up(extra_env=None):
    files = list(COMPOSE)
    if extra_env:
        override = Path(tempfile.gettempdir()) / f"qa_cl03_override_{int(time.time())}.yml"
        lines = ["services:", "  api:", "    environment:"] + [f"      {k}: \"{v}\"" for k, v in extra_env.items()]
        override.write_text("\n".join(lines) + "\n")
        files += ["-f", str(override)]
    subprocess.run(files + ["up", "-d"], capture_output=True, check=True, cwd=ROOT)
    time.sleep(2)


def login_raw(e, pw, headers=None):
    return req("POST", "/users/login", json_body={"email": e, "password": pw}, headers=headers)


def series(fn, n):
    return [fn().status_code for _ in range(n)]


S = {}


def prepare_user(tag):
    e = email(tag)
    register(e)
    return e


# ───────────────────────── 1. Limits per endpoint ─────────────────────────

def s_limits():
    reset()
    e = prepare_user("rl")
    S["e"] = e
    S["uid"] = int(sql1(f"SELECT id FROM users WHERE lower(email) = lower('{e}');"))

    reset()
    codes = series(lambda: login_raw(e, "WrongPass1"), 6)
    check("RL-01", 429 not in codes[:5] and codes[5] == 429, f"codes: {codes}")

    reset()
    emails = [email(f"rl02_{i}") for i in range(4)]
    codes = [register(x).status_code for x in emails]
    fourth = sql1(f"SELECT count(*) FROM users WHERE lower(email) = lower('{emails[3]}');")
    check("RL-02", codes[:3] == [201, 201, 201] and codes[3] == 429 and fourth == "0", f"codes: {codes}; 4th user in DB: {fourth}")

    reset()
    codes = series(lambda: req("POST", "/users/refresh", cookie="random-token"), 101)
    check("RL-03", 429 not in codes[:100] and codes[100] == 429, f"1–100: {sorted(set(codes[:100]))}, 101st: {codes[100]}")

    reset()
    codes = series(lambda: req("POST", "/users/logout"), 101)
    check("RL-04", 429 not in codes[:100] and codes[100] == 429, f"1–100: {sorted(set(codes[:100]))}, 101st: {codes[100]}")

    reset()
    _, tok, _ = login(e)
    codes = series(lambda: req("POST", "/users/logout-all", headers=bearer(tok)), 101)
    check("RL-05", 429 not in codes[:100] and codes[100] == 429, f"1–100: {sorted(set(codes[:100]))}, 101st: {codes[100]}")

    reset()
    codes = series(lambda: req("GET", "/health"), 101)
    check("RL-06", 429 not in codes[:100] and codes[100] == 429, f"1–100: {sorted(set(codes[:100]))}, 101st: {codes[100]}")

    reset()
    _, tok, _ = login(e)
    S["tok"] = tok
    codes = series(lambda: req("GET", "/items/", headers=bearer(tok)), 61)
    check("RL-07", 429 not in codes[:60] and codes[60] == 429, f"1–60: {sorted(set(codes[:60]))}, 61st: {codes[60]}")

    reset()
    codes = series(lambda: req("GET", "/items/all", headers=bearer(tok)), 61)
    check("RL-08", 429 not in codes[:60] and codes[60] == 429, f"1–60: {sorted(set(codes[:60]))}, 61st: {codes[60]}")

    reset()
    before = int(sql1(f"SELECT count(*) FROM items WHERE owner_id={S['uid']};"))
    codes = [req("POST", "/items/", json_body={"title": f"rl{i}", "description": "d"}, headers=bearer(tok)).status_code for i in range(31)]
    created = int(sql1(f"SELECT count(*) FROM items WHERE owner_id={S['uid']};")) - before
    check("RL-09", codes[:30] == [201] * 30 and codes[30] == 429 and created == 30, f"1–30: {sorted(set(codes[:30]))}, 31st: {codes[30]}; created: {created}")

    reset()
    iid = int(sql1(f"SELECT id FROM items WHERE owner_id={S['uid']} AND NOT is_deleted ORDER BY id DESC LIMIT 1;"))
    codes = [req("PUT", f"/items/{iid}", json_body={"title": f"v{i}", "description": "d"}, headers=bearer(tok)).status_code for i in range(31)]
    title = sql1(f"SELECT title FROM items WHERE id={iid};")
    check("RL-10", 429 not in codes[:30] and codes[30] == 429 and title == "v29", f"1–30: {sorted(set(codes[:30]))}, 31st: {codes[30]}; title = {title}")

    reset()
    rows = sql(f"INSERT INTO items (title, description, owner_id, is_deleted, created_at, updated_at) "
               f"SELECT 'del'||g, 'd', {S['uid']}, false, now(), now() FROM generate_series(1,31) g RETURNING id;")
    ids = [int(x[0]) for x in rows if x[0].isdigit()]  # psql also prints the "INSERT 0 31" status line
    codes = [req("DELETE", f"/items/{i}", headers=bearer(tok)).status_code for i in ids]
    alive = sql1(f"SELECT NOT is_deleted FROM items WHERE id={ids[30]};")
    ok = 429 not in codes[:30] and codes[30] == 429 and alive == "t"
    check("RL-11", ok, f"1–30: {sorted(set(codes[:30]))}, 31st: {codes[30]}; 31st item not deleted: {alive == 't'}",
          "" if ok else "the limit counter is kept per URL path (slowapi key_style='url'): every /items/{id} has its own "
          "counter, so PUT / DELETE across different items are not limited")

    reset()
    d = series(lambda: req("GET", "/docs"), 101)
    o = series(lambda: req("GET", "/openapi.json"), 101)
    check("RL-12", True, f"/docs 101st → {d[100]}, /openapi.json 101st → {o[100]}",
          "default_limits (100/minute) applies to undecorated endpoints via SlowAPIMiddleware" if 429 in d + o
          else "endpoints without a decorator are not rate-limited")


# ───────────────────────── 2. 429 format ─────────────────────────

def s_format():
    reset()
    e = S["e"]
    series(lambda: login_raw(e, "WrongPass1"), 5)
    r = login_raw(e, "WrongPass1")
    S["r429"] = r
    b = body(r)
    check("RL-13", r.status_code == 429, short(r))
    check("RL-14", isinstance(b, dict) and "error" in b, short(r))
    check("RL-15", isinstance(b, dict) and "detail" in b, f"429 body: {b}; other errors use {{\"detail\": …}}",
          "" if isinstance(b, dict) and "detail" in b else "the 429 error format ({\"error\": …}) differs from all other API errors ({\"detail\": …})")
    check("RL-16", (r.headers.get("content-type") or "").startswith("application/json"), r.headers.get("content-type"))
    ra = r.headers.get("retry-after")
    check("RL-17", ra is not None and ra.isdigit(), f"Retry-After: {ra}", "" if ra else "no Retry-After header: the client cannot know when to retry")
    reset()
    ok = login_raw(e, "WrongPass1")
    xr = {k: v for k, v in ok.headers.items() if k.lower().startswith("x-ratelimit")}
    x429 = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
    check("RL-18", bool(xr) and bool(x429), f"X-RateLimit-* in a normal response: {xr or 'none'}; in 429: {x429 or 'none'}",
          "" if xr else "rate limit headers are disabled (slowapi headers_enabled=False)")
    spec = client.get("/openapi.json").json()
    documented = [f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m, op in ops.items() if "429" in op.get("responses", {})]
    check("RL-19", bool(documented), f"endpoints documenting 429: {documented or 'none'}")
    check("RL-20", not any(k in r.text for k in ("Traceback", "/app/", "File \"")), short(r))


# ───────────────────────── 3. Window and reset ─────────────────────────

def s_window():
    e = S["e"]
    reset()
    t0 = time.time()
    series(lambda: login_raw(e, "WrongPass1"), 5)
    blocked = login_raw(e, "WrongPass1").status_code
    time.sleep(max(0, 61 - (time.time() - t0)))
    after = login_raw(e, "WrongPass1").status_code
    check("RL-21", blocked == 429 and after != 429, f"6th → {blocked}; after 61 s → {after}")

    reset()
    t0 = time.time()
    series(lambda: login_raw(e, "WrongPass1"), 5)
    probes = {}
    for sec in (10, 20, 30, 40, 50):
        time.sleep(max(0, sec - (time.time() - t0)))
        probes[sec] = login_raw(e, "WrongPass1").status_code
    check("RL-22", probes[30] == 429, f"probe at ~30 s → {probes[30]}")
    time.sleep(max(0, 61 - (time.time() - t0)))
    final = login_raw(e, "WrongPass1").status_code
    check("RL-23", final != 429, f"probes every 10 s: {probes}; at 61 s from the first request → {final}")

    reset()
    t0 = time.time()
    codes = [login_raw(e, "WrongPass1").status_code]
    time.sleep(max(0, 57 - (time.time() - t0)))
    codes += series(lambda: login_raw(e, "WrongPass1"), 4)
    time.sleep(max(0, 61 - (time.time() - t0)))
    codes += series(lambda: login_raw(e, "WrongPass1"), 5)
    span = time.time() - t0 - 57
    passed = sum(1 for c in codes[1:] if c != 429)
    check("RL-24", True, f"1 request at 0 s, 4 at ~57 s, 5 at ~61 s → codes {codes}; {passed} requests passed within ~{span:.0f} s",
          "fixed window from the first request: up to 2×N requests can pass around the window boundary")

    reset()
    codes = []
    t0 = time.time()
    for i in range(10):
        time.sleep(max(0, i * 12 - (time.time() - t0)))
        codes.append(login_raw(e, "WrongPass1").status_code)
    check("RL-25", 429 not in codes, f"10 logins at 12 s intervals → {sorted(set(codes))}")


# ───────────────────────── 4. Counter independence ─────────────────────────

def s_independence():
    e = S["e"]
    reset()
    series(lambda: login_raw(e, "WrongPass1"), 6)
    r = register(email("rl26"))
    check("RL-26", r.status_code == 201, f"login exhausted → register {r.status_code}")

    reset()
    _, tok, _ = login(e)
    codes = [req("POST", "/items/", json_body={"title": "x", "description": "d"}, headers=bearer(tok)).status_code for _ in range(31)]
    g = req("GET", "/items/", headers=bearer(tok)).status_code
    put_c = req("PUT", f"/items/{body(req('GET', '/items/', headers=bearer(tok)))[0]['id']}",
                json_body={"title": "y", "description": "d"}, headers=bearer(tok)).status_code
    check("RL-27", codes[30] == 429 and g == 200, f"POST exhausted (31st → {codes[30]}) → GET /items/ {g}")
    check("RL-29", True, f"POST exhausted → PUT {put_c}", "separate counters per route" if put_c != 429 else "shared counter")

    reset()
    _, tok, _ = login(e)
    series(lambda: req("GET", "/items/", headers=bearer(tok)), 61)
    a = req("GET", "/items/all", headers=bearer(tok)).status_code
    check("RL-28", a == 200, f"GET /items/ exhausted → GET /items/all {a}", "separate counters per route" if a == 200 else "")

    reset()
    _, ta, _ = login(e)
    eb = prepare_user("rlB")
    _, tb, _ = login(eb)
    series(lambda: req("GET", "/items/", headers=bearer(ta)), 61)
    b = req("GET", "/items/", headers=bearer(tb)).status_code
    check("RL-30", b == 429, f"User A exhausted GET /items/ → User B (same IP) → {b}",
          "the key is the client IP: users behind one NAT / office IP block each other")

    reset()
    codes = [login_raw(email(f"rl31_{i}"), "x").status_code for i in range(6)]
    check("RL-31", 429 not in codes[:5] and codes[5] == 429, f"6 different emails → {codes}")

    reset()
    series(lambda: login_raw(e, "WrongPass1"), 6)
    inner = [in_container_login(e, "WrongPass1") for _ in range(5)]
    check("RL-32", 429 in inner, f"host IP exhausted for {e.split('@')[0]}…; same account from another IP (container) → {inner}",
          "" if 429 in inner else "no per-account limit: each additional IP gets 5 more password attempts per minute")


# ───────────────────────── 5. Which requests are counted ─────────────────────────

def s_counted():
    e = S["e"]
    reset()
    codes = series(lambda: login_raw(e, "WrongPass1"), 6)
    check("RL-33", codes[:5] == [401] * 5 and codes[5] == 429, f"codes: {codes}")

    reset()
    codes = series(lambda: req("POST", "/users/login", json_body={"email": "abc", "password": "x"}), 10)
    after = login_raw(e, "WrongPass1").status_code
    check("RL-34", 429 in codes, f"10 × invalid body → {sorted(set(codes))}; then a valid login → {after}",
          "" if 429 in codes else "requests rejected by body validation (422) are not counted — the limit can be bypassed")

    reset()
    codes = series(lambda: register(e), 4)
    check("RL-35", codes[:3] == [400] * 3 and codes[3] == 429, f"duplicate registrations → {codes}")

    reset()
    codes = series(lambda: req("GET", "/items/"), 61)
    _, tok, _ = login(e)
    after = req("GET", "/items/", headers=bearer(tok)).status_code
    check("RL-36", 429 in codes, f"61 × GET /items/ without a token → {sorted(set(codes))}; then with a token → {after}",
          "" if 429 in codes else "requests rejected by authentication are not rate-limited")

    reset()
    codes = series(lambda: req("GET", "/items/", headers=bearer("invalid")), 61)
    check("RL-37", 429 in codes, f"61 × GET /items/ with an invalid token → {sorted(set(codes))}",
          "" if 429 in codes else "requests with an invalid token are not rate-limited (token brute force is unlimited)")

    reset()
    uid = S["uid"]
    before = int(sql1(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid};"))
    codes = series(lambda: login_raw(e, "Passw0rd!"), 6)
    after = int(sql1(f"SELECT count(*) FROM refresh_tokens WHERE user_id={uid};"))
    check("RL-38", codes[5] == 429 and after - before == 5,
          f"6 correct logins → {codes}; new refresh tokens: {after - before} (RL-02: 4th user not created, RL-09: exactly 30 items)")

    reset()
    series(lambda: login_raw(e, "WrongPass1"), 6)
    db = sql1("SELECT count(*) FROM logs WHERE status_code=429 OR message ILIKE '%rate limit%';")
    console = subprocess.run(["docker", "logs", "--since", "30s", "fastapi_api"], capture_output=True, text=True)
    con = "ratelimit" in (console.stdout + console.stderr).lower() or "rate limit" in (console.stdout + console.stderr).lower()
    check("RL-39", db != "0" or con, f"logs table records: {db}; console mentions: {con}",
          "" if db != "0" or con else "rate limit violations are not logged anywhere")


# ───────────────────────── 6. Configuration and bypass ─────────────────────────

def s_config():
    e = S["e"]
    compose_up({"LOGIN_RATE_LIMIT": "2/minute"})
    wait_ready()
    codes = series(lambda: login_raw(e, "WrongPass1"), 3)
    check("RL-40", codes[:2] == [401, 401] and codes[2] == 429, f"LOGIN_RATE_LIMIT=2/minute → {codes}")

    compose_up({"LOGIN_RATE_LIMIT": "abc"})
    time.sleep(3)
    state = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", "fastapi_api"], capture_output=True, text=True).stdout.strip()
    applied = subprocess.run(["docker", "exec", "fastapi_api", "printenv", "LOGIN_RATE_LIMIT"], capture_output=True, text=True).stdout.strip()
    h = in_container("/health")
    codes = series(lambda: login_raw(e, "WrongPass1"), 8) if h == 200 else []
    logs = subprocess.run(["docker", "logs", "--since", "20s", "fastapi_api"], capture_output=True, text=True)
    err = [l for l in (logs.stdout + logs.stderr).splitlines() if "abc" in l or "Error" in l][:2]
    silent = h == 200 and codes and 500 not in codes
    check("RL-42", not silent, f"LOGIN_RATE_LIMIT={applied!r}: container {state}, /health → {h}, 8 logins → {codes or '-'}; "
          f"log: {err or 'no error lines'}",
          "" if not silent else ("an invalid limit value is silently accepted and the login limit is disabled"
                                 if 429 not in codes else "an invalid limit value is silently ignored"))
    S["rl42"] = (state, h, codes)

    compose_up()
    wait_ready()
    reset()
    series(lambda: login_raw(e, "WrongPass1"), 6)
    reset()
    after = login_raw(e, "WrongPass1").status_code
    check("RL-41", after != 429, f"exhausted → docker restart → login {after}",
          "counters are in-memory: a restart resets them; with several workers or instances limits would not be shared")

    reset()
    series(lambda: login_raw(e, "WrongPass1"), 6)
    xff = [login_raw(e, "WrongPass1", headers={"X-Forwarded-For": ip}).status_code for ip in ("1.2.3.4", "5.6.7.8", "9.9.9.9")]
    check("RL-43", all(c == 429 for c in xff), f"with X-Forwarded-For spoofing → {xff}")
    xri = [login_raw(e, "WrongPass1", headers={"X-Real-IP": ip}).status_code for ip in ("1.2.3.4", "5.6.7.8")]
    check("RL-44", all(c == 429 for c in xri), f"with X-Real-IP spoofing → {xri}")

    reset()
    _, tok, _ = login(e)
    series(lambda: req("GET", "/items/", headers=bearer(tok)), 61)
    variants = {"/items": req("GET", "/items", headers=bearer(tok)).status_code,
                "/items/?x=1": req("GET", "/items/?x=1", headers=bearer(tok)).status_code,
                "/ITEMS/": req("GET", "/ITEMS/", headers=bearer(tok)).status_code}
    check("RL-45", 200 not in variants.values(), f"after exhausting /items/: {variants}")

    ips = sql1("SELECT count(*) FILTER (WHERE ip IS NOT NULL) || '/' || count(*) FROM logs;")
    check("RL-46", True, f"logs records with ip: {ips}; all host clients share one counter (RL-30)",
          "requests from the host reach the container through the Docker gateway, so all clients of the stand share "
          "one limit; logs.ip is never filled, so the client IP cannot be checked from the logs")

    check("RL-47", False, "key_func=get_remote_address → request.client.host; uvicorn runs without --proxy-headers / "
          "--forwarded-allow-ips; X-Forwarded-For is ignored (RL-43)",
          "behind a reverse proxy every user gets the proxy IP and therefore one shared limit — one client can block login for everyone")


# ───────────────────────── 7. Scenarios ─────────────────────────

def s_e2e():
    e = S["e"]
    reset()
    t0 = time.time()
    codes = series(lambda: login_raw(e, "WrongPass1"), 20)
    right = login_raw(e, "Passw0rd!").status_code
    time.sleep(max(0, 61 - (time.time() - t0)))
    later = login_raw(e, "Passw0rd!").status_code
    ok = codes[:5] == [401] * 5 and set(codes[5:]) == {429} and right == 429 and later == 200
    check("E2E-01", ok, f"20 wrong → 1–5 {sorted(set(codes[:5]))}, 6–20 {sorted(set(codes[5:]))}; correct password → {right}; after the window → {later}")

    reset()
    r, tok, rc = login(e)
    s = [r.status_code] + [req("GET", "/items/", headers=bearer(tok)).status_code for _ in range(10)]
    s += [req("POST", "/items/", json_body={"title": "n", "description": "d"}, headers=bearer(tok)).status_code for _ in range(5)]
    rr = req("POST", "/users/refresh", cookie=rc)
    s += [rr.status_code, req("POST", "/users/logout", cookie=refresh_cookie(rr)).status_code]
    check("E2E-02", 429 not in s, f"login, 10 × GET, 5 × POST, refresh, logout → {sorted(set(s))}")

    reset()
    _, tok, _ = login(e)
    before = int(sql1(f"SELECT count(*) FROM items WHERE owner_id={S['uid']};"))
    codes = [req("POST", "/items/", json_body={"title": f"spam{i}", "description": "d"}, headers=bearer(tok)).status_code for i in range(40)]
    created = int(sql1(f"SELECT count(*) FROM items WHERE owner_id={S['uid']};")) - before
    check("E2E-03", codes.count(201) == 30 and codes.count(429) == 10 and created == 30,
          f"40 × POST → 201: {codes.count(201)}, 429: {codes.count(429)}; created: {created}")


def merge_into_today(cl):
    import json
    from datetime import datetime
    path = OUT_DIR / f"{cl}_{datetime.now():%Y-%m-%d}.json"
    data = json.loads(path.read_text())
    data["results"] = {k: v for k, v in data["results"].items() if not k.startswith("_error_")}
    data["results"].update(results)
    order = lambda k: (k.split("-")[0] != "RL", int(k.split("-")[1]) if k.split("-")[1].isdigit() else 0)
    data["results"] = dict(sorted(data["results"].items(), key=lambda kv: order(kv[0])))
    data.setdefault("reruns", []).append({"run_id": RUN_ID, "sections": sys.argv[1:], "checks": sorted(results)})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    counts = {}
    for v in data["results"].values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(f"\nMerged into {path}: {counts}")


def main():
    wait_ready()
    env = subprocess.run(["docker", "exec", "fastapi_api", "printenv", "LOGIN_RATE_LIMIT"], capture_output=True, text=True).stdout.strip()
    if env != "5/minute":
        sys.exit(f"Expected default limits (LOGIN_RATE_LIMIT=5/minute), got {env!r}. Start the stand without the functional override.")
    all_sections = (s_limits, s_format, s_window, s_independence, s_counted, s_config, s_e2e)
    only = sys.argv[1:]  # e.g. s_limits s_config — re-run selected sections and merge into today's results
    print("CL-03 Rate Limit run" + (f" (sections: {', '.join(only)})" if only else "") + "\n", flush=True)
    if only and "s_limits" not in only:
        reset(); S["e"] = prepare_user("rl"); S["uid"] = int(sql1(f"SELECT id FROM users WHERE lower(email) = lower('{S['e']}');"))
    for fn in all_sections:
        if only and fn.__name__ not in only:
            continue
        print(f"── {fn.__name__}", flush=True)
        section(fn)
    if only:
        merge_into_today("CL-03")
    else:
        save("CL-03", "CL-03 Rate Limiting", "Local (Docker), default limits from .env")


if __name__ == "__main__":
    main()
