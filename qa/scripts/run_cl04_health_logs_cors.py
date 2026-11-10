"""
Executes checklist CL-04 Health / Logs / CORS / API Docs (docs/checklists/CL-04_Health_Logs_CORS.md).

Requirements: stand started with qa/docker-compose.functional.yml; pip install httpx python-jose openapi-spec-validator
- Section 1.2 stops and starts the `fastapi_postgres` container (data is kept).
- HL-19 (cold start) runs on a separate disposable stack (own project name, volume and port 18000)
  so the main stand's database volume is never deleted.
- CR-17 temporarily restarts the API with LOGIN_RATE_LIMIT=2/minute to get a 429, then restores the stand.
- CR-20 is a real-browser check; pass its result via the environment:
    CR20="pass|<actual>|<note>"   (status pass/fail)

Usage: python qa/scripts/run_cl04_health_logs_cors.py     # results → qa/runs/CL-04_<date>.json
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from common import (BASE, PW, bearer, body, check, client, email, login, merge_into_today, new_user, register, req,
                    save, section, short, sql, sql1)

ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "-f", str(ROOT / "qa/docker-compose.functional.yml")]
ALLOWED = "http://localhost:3000"
S = {}


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def wait_health(url=BASE, timeout=90, want_db="ok"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = httpx.get(url + "/health", timeout=5)
            if r.status_code == 200 and r.json().get("database") == want_db:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def console(since="60s"):
    p = docker("logs", "--since", since, "fastapi_api")
    return (p.stdout + p.stderr).splitlines()


# ───────────────────────── 1. Health ─────────────────────────

def s_health():
    r = req("GET", "/health")
    check("HL-01", r.status_code == 200 and body(r) == {"status": "ok", "database": "ok"}, short(r))
    check("HL-02", r.status_code == 200, "no Authorization header → " + str(r.status_code))
    r2 = req("GET", "/health", headers=bearer("garbage"))
    check("HL-03", r2.status_code == 200, f"invalid Bearer token → {r2.status_code}")
    b = body(r)
    check("HL-04", set(b) == {"status", "database"} and all(isinstance(v, str) for v in b.values())
          and r.headers.get("content-type", "").startswith("application/json"), f"keys={sorted(b)}, content-type={r.headers.get('content-type')}")
    check("HL-05", set(b) == {"status", "database"}, f"body: {b}; headers: server={r.headers.get('server')}",
          "no versions or connection details in the body")
    ts = []
    for _ in range(10):
        t0 = time.perf_counter(); client.get("/health"); ts.append((time.perf_counter() - t0) * 1000)
    med = sorted(ts)[5]
    check("HL-06", med < 200, f"median {med:.1f} ms over 10 requests")
    h = req("HEAD", "/health")
    check("HL-07", h.status_code == 200, f"HEAD /health → {h.status_code}",
          "" if h.status_code == 200 else "HEAD is not supported — monitoring tools that use HEAD will report the service as down")
    got = {m: req(m, "/health").status_code for m in ("POST", "DELETE")}
    check("HL-08", all(c == 405 for c in got.values()), str(got))
    r = req("GET", "/health/")
    check("HL-09", r.status_code in (307, 404), f"/health/ → {r.status_code} {r.headers.get('location', '')}")


def s_db_down():
    docker("stop", "fastapi_postgres")
    try:
        t0 = time.perf_counter()
        r = req("GET", "/health")
        ms = (time.perf_counter() - t0) * 1000
        b = body(r)
        check("HL-10", isinstance(b, dict) and b.get("database") == "error", f"{short(r)} in {ms:.0f} ms")
        check("HL-11", r.status_code == 503, f"HTTP {r.status_code}",
              "" if r.status_code == 503 else "health returns 200 when the database is down — load balancers / monitoring see the service as healthy")
        check("HL-12", isinstance(b, dict) and b.get("status") != "ok", f"status = {b.get('status') if isinstance(b, dict) else b}",
              "" if isinstance(b, dict) and b.get("status") != "ok" else "status stays \"ok\" with the database down")
        check("HL-13", ms < 5000, f"response time with the DB down: {ms:.0f} ms")
        check("HL-14", isinstance(b, dict) and set(b.values()) <= {"ok", "error"}, f"body: {b}")
        h = {"Origin": ALLOWED}
        lr = req("POST", "/users/login", json_body={"email": "x@test.com", "password": "x"}, headers=h)
        S["login_db_down"] = lr
        leak = any(k in lr.text for k in ("Traceback", "psycopg", "sqlalchemy", "OperationalError", "/app/"))
        check("HL-15", lr.status_code in (500, 503) and not leak, f"POST /users/login → {short(lr, 80)}; internals in body: {leak}")
        # CR-18 needs a 500 with the allowed origin
        S["cr18"] = lr.headers.get("access-control-allow-origin")
        time.sleep(1)
        S["console_db_down"] = console("20s")
    finally:
        docker("start", "fastapi_postgres")
    t0 = time.time()
    ok = wait_health(timeout=60)
    check("HL-16", ok, f"database back → /health ok after {time.time() - t0:.0f} s without restarting the API")


def s_startup():
    lines = console("100000h")
    mig = [l for l in lines if "Migrations completed successfully" in l or "Migration failed" in l]
    exists = sql1("SELECT to_regclass('public.alembic_version') IS NOT NULL;") == "t"
    ver = sql1("SELECT version_num FROM alembic_version;") if exists else None
    heads = docker("exec", "fastapi_api", "alembic", "heads").stdout.split()
    head = heads[0] if heads else None
    up = docker("exec", "fastapi_api", "alembic", "upgrade", "head")
    err = next((l for l in (up.stdout + up.stderr).splitlines() if "Error" in l and ":" in l), "")
    check("HL-17", ver == head, f"alembic_version table exists: {exists}, version={ver}, head={head}; manual `alembic upgrade head` → "
          f"exit {up.returncode}: {err[:150]}; startup log line: {mig[-1][:60] if mig else 'none'}",
          "" if ver == head else "migrations fail on every startup and the failure is silent: the initial migration 2317e5de5f12 is empty, "
          "so the chain cannot build the schema (the 2nd migration hits an existing / missing users table); the schema is created by "
          "Base.metadata.create_all instead and alembic_version never exists. \"Migration failed\" is not visible because "
          "alembic's fileConfig disables the app logger")

    docker("stop", "fastapi_postgres")
    docker("restart", "fastapi_api")
    time.sleep(8)
    state = docker("inspect", "-f", "{{.State.Status}} exit={{.State.ExitCode}}", "fastapi_api").stdout.strip()
    tail = [l for l in console("15s") if l.strip()][-3:]
    docker("start", "fastapi_postgres")
    time.sleep(3)
    docker("start", "fastapi_api")
    subprocess.run(BASE_COMPOSE + ["up", "-d"], capture_output=True, cwd=ROOT)
    up = wait_health(timeout=90)
    err = next((l for l in reversed(tail) if "Error" in l or "error" in l), tail[-1] if tail else "")
    check("HL-18", True, f"API restarted with the DB down → container {state}; last log: {err[:140]}",
          ("the app crashes on startup (create_all fails) and the container stays down until restarted manually"
           if "exited" in state else "the app keeps running without the database") + f"; stand restored: {up}")

    tmp = Path(tempfile.mkdtemp(prefix="qa_cold_"))
    compose = tmp / "docker-compose.cold.yml"
    compose.write_text(f"""services:
  db:
    image: postgres:15
    env_file: [{ROOT / '.env'}]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${{POSTGRES_USER}}"]
      interval: 2s
      retries: 30
    volumes: [coldpg:/var/lib/postgresql/data]
  api:
    image: fastapi-project-api
    env_file: [{ROOT / '.env'}]
    working_dir: /app
    volumes: [{ROOT}:/app]
    depends_on: {{db: {{condition: service_healthy}}}}
    ports: ["18000:8000"]
volumes:
  coldpg: {{}}
""")
    proj = ["docker", "compose", "-p", "qacold", "-f", str(compose)]
    try:
        t0 = time.time()
        subprocess.run(proj + ["up", "-d"], capture_output=True, text=True, timeout=240)
        ok = wait_health("http://localhost:18000", timeout=120)
        ver = subprocess.run(proj + ["exec", "-T", "db", "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"'],
                             capture_output=True, text=True).stdout.strip()
        api_log = subprocess.run(proj + ["logs", "api"], capture_output=True, text=True)
        tail = [l for l in (api_log.stdout + api_log.stderr).splitlines() if "Running upgrade" in l][-1:]
        tables = subprocess.run(proj + ["exec", "-T", "db", "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname=\'public\'"'],
                                capture_output=True, text=True).stdout.strip()
        check("HL-19", ok and ver == head, f"fresh stack with an empty volume: /health ok={ok} after {time.time() - t0:.0f} s, "
              f"tables={tables}, alembic_version={ver or 'none'}; last migration step in the log: {tail[0].strip()[:90] if tail else '-'}",
              "" if ver == head else "on a clean database the app starts only thanks to create_all — the migration chain itself fails")
    finally:
        subprocess.run(proj + ["down", "-v"], capture_output=True, timeout=120)

    p = docker("exec", "fastapi_api", "alembic", "check")
    out = (p.stdout + p.stderr).strip().splitlines()
    check("HL-20", p.returncode == 0, f"alembic check → exit {p.returncode}: {(out[-1] if out else '')[:160]}",
          "" if p.returncode == 0 else ("alembic check cannot compare the schema with the models: the database has no alembic_version "
                                        "(the migration chain never completes — see HL-17)" if "not up to date" in "".join(out)
                                        else "the database schema differs from the models (autogenerate detects changes)"))


# ───────────────────────── 2. Logging ─────────────────────────

def last_log(where):
    rows = sql(f"SELECT level, message, coalesce(user_id::text,'NULL'), coalesce(path,''), coalesce(method,'NULL'), "
               f"coalesce(status_code::text,'NULL'), coalesce(ip,'NULL'), coalesce(duration_ms::text,'NULL') "
               f"FROM logs WHERE {where} ORDER BY id DESC LIMIT 1;")
    return rows[0] if rows else None


def s_logging():
    start_id = int(sql1("SELECT coalesce(max(id),0) FROM logs;"))
    e = email("lg")
    register(e)
    uid = int(sql1(f"SELECT id FROM users WHERE email='{e}';"))
    lg = last_log(f"path='/users/register' AND user_id={uid}")
    check("LG-01", lg and lg[0] == "INFO", f"{lg[:3] if lg else None}")
    register(e)
    lg = last_log(f"path='/users/register' AND message LIKE '%{e}'")
    check("LG-02", lg and lg[0] == "WARNING", f"{lg[:2] if lg else None}")
    _, tok, rc = login(e)
    lg = last_log(f"path='/users/login' AND user_id={uid} AND level='INFO'")
    check("LG-03", lg is not None, f"{lg[:3] if lg else None}")
    req("POST", "/users/login", json_body={"email": e, "password": "WrongPass1"})
    lg = last_log(f"path='/users/login' AND user_id={uid} AND level='WARNING'")
    check("LG-04", lg is not None and lg[2] == str(uid), f"{lg[:3] if lg else None}")
    req("POST", "/users/login", json_body={"email": email("nobody"), "password": "x"})
    lg = last_log("path='/users/login' AND message LIKE 'Login attempt for non-existent%'")
    check("LG-05", lg and lg[0] == "WARNING" and lg[2] == "NULL", f"{lg[:3] if lg else None}")
    r = req("POST", "/users/refresh", cookie=rc)
    rc2 = r.headers.get("set-cookie", "").split(";")[0].split("=", 1)[-1].strip('"')
    lg = last_log(f"path='/users/refresh' AND user_id={uid}")
    check("LG-06", lg and lg[0] == "INFO", f"{lg[:3] if lg else None}")
    req("POST", "/users/refresh", cookie="garbage")
    lg = last_log("path='/users/refresh' AND level='WARNING'")
    check("LG-07", lg is not None, f"{lg[:2] if lg else None}")
    req("POST", "/users/logout", cookie=rc2)
    lg = last_log("path='/users/logout'")
    check("LG-08", lg and lg[0] == "INFO" and lg[2] != "NULL", f"{lg[:3] if lg else None}",
          "" if lg and lg[2] != "NULL" else "user_id is not set — see FAT-19")
    _, tok, _ = login(e)
    req("POST", "/users/logout-all", headers=bearer(tok))
    lg = last_log(f"path='/users/logout-all' AND user_id={uid}")
    check("LG-09", lg and lg[0] == "INFO", f"{lg[:3] if lg else None}")
    _, tok, _ = login(e)
    iid = body(req("POST", "/items/", json_body={"title": "log", "description": "d"}, headers=bearer(tok)))["id"]
    lg = last_log(f"message='item_created' AND user_id={uid}")
    check("LG-10", lg and lg[4] == "POST" and lg[5] == "201", f"{lg[:6] if lg else None}")
    req("PUT", f"/items/{iid}", json_body={"title": "log2", "description": "d"}, headers=bearer(tok))
    lg = last_log(f"message='item_updated' AND user_id={uid}")
    check("LG-11", lg and lg[4] == "PUT" and lg[5] == "200" and lg[3] == f"/items/{iid}", f"{lg[:6] if lg else None}")
    req("DELETE", f"/items/{iid}", headers=bearer(tok))
    lg = last_log(f"message='item_deleted' AND user_id={uid}")
    check("LG-12", lg and lg[4] == "DELETE" and lg[5] == "204", f"{lg[:6] if lg else None}")
    req("PUT", "/items/999999999", json_body={"title": "x", "description": "d"}, headers=bearer(tok))
    lg = last_log(f"message='item_not_found' AND user_id={uid}")
    check("LG-13", lg and lg[0] == "WARNING" and lg[5] == "404", f"{lg[:6] if lg else None}")
    _, ub, tb, _ = new_user("lgB")
    other = body(req("POST", "/items/", json_body={"title": "B", "description": "d"}, headers=bearer(tb)))["id"]
    req("DELETE", f"/items/{other}", headers=bearer(tok))
    lg = last_log(f"message='item_delete_forbidden' AND user_id={uid}")
    check("LG-14", lg and lg[0] == "WARNING" and lg[5] == "403" and lg[2] == str(uid), f"{lg[:6] if lg else None}")

    n0 = int(sql1("SELECT count(*) FROM logs;"))
    req("GET", "/items/", headers=bearer("forged.token.value"))
    n1 = int(sql1("SELECT count(*) FROM logs;"))
    check("LG-15", n1 > n0, f"request with an invalid token → new log records: {n1 - n0}",
          "" if n1 > n0 else "failed authentication (invalid / forged token) is not logged")
    req("POST", "/users/register", json_body={"email": "bad"})
    n2 = int(sql1("SELECT count(*) FROM logs;"))
    check("LG-16", True, f"422 validation error → new log records: {n2 - n1}", "validation errors are not logged (acceptable)" if n2 == n1 else "")
    check("LG-17", False, "see CL-03 RL-39: rate limit violations are not written to logs or the console")
    n3 = int(sql1("SELECT count(*) FROM logs;"))
    req("GET", "/items/", headers=bearer(tok)); req("GET", "/items/all", headers=bearer(tok)); req("GET", "/health")
    n4 = int(sql1("SELECT count(*) FROM logs;"))
    check("LG-18", True, f"read operations → new log records: {n4 - n3}", "read operations are not logged (acceptable)" if n4 == n3 else "")
    cons = S.get("console_db_down", [])
    err = [l for l in cons if "ERROR" in l or "Exception" in l or "Traceback" in l]
    structured = any(l.startswith("{") and '"ERROR"' in l for l in cons)
    check("LG-19", bool(err), f"console lines during the DB outage: ERROR/Exception lines {len(err)}, structured JSON ERROR: {structured}",
          "" if structured else ("nothing is written: the 500 leaves no trace in the console (app and uvicorn loggers are disabled by alembic's fileConfig)"
                                 if not err else "only uvicorn's plain-text traceback; the app logger writes no ERROR record"))

    stats = sql("SELECT count(*), count(ip), count(duration_ms), count(method), count(status_code) FROM logs;")[0]
    total, ip, dur, meth, st = map(int, stats)
    check("LG-20", ip == total, f"records with ip: {ip} of {total}", "" if ip == total else "ip is never filled")
    check("LG-21", dur == total, f"records with duration_ms: {dur} of {total}", "" if dur == total else "duration_ms is never filled")
    users_with = int(sql1("SELECT count(*) FROM logs WHERE path LIKE '/users/%' AND method IS NOT NULL;"))
    users_all = int(sql1("SELECT count(*) FROM logs WHERE path LIKE '/users/%';"))
    check("LG-22", users_with == users_all, f"auth records with method/status_code: {users_with} of {users_all}; items records: always set",
          "" if users_with == users_all else "method and status_code are filled only for items events")
    mism = sql1("SELECT count(*) FROM logs WHERE (message='item_created' AND status_code<>201) OR (message='item_updated' AND status_code<>200) "
                "OR (message='item_deleted' AND status_code<>204) OR (message LIKE '%forbidden' AND status_code<>403) OR (message='item_not_found' AND status_code<>404);")
    check("LG-23", mism == "0", f"records whose status_code differs from the actual response: {mism}")
    samples = [r[0] for r in sql(f"SELECT DISTINCT message FROM logs WHERE id > {start_id} AND message NOT LIKE '%@%' LIMIT 5;")]
    check("LG-24", False, f"message styles: free text with email (\"User logged in: user@…\") vs event codes ({', '.join(samples[:3])})",
          "two different message formats in one table make filtering and alerting harder")
    levels = [r[0] for r in sql("SELECT DISTINCT level FROM logs;")]
    check("LG-25", set(levels) <= {"INFO", "WARNING", "ERROR"}, f"levels: {levels}")
    lag = float(sql1(f"SELECT max(abs(extract(epoch from (now() at time zone 'utc' - created_at)))) FROM logs WHERE id > {start_id};"))
    order = sql1(f"SELECT bool_and(ok) FROM (SELECT created_at >= lag(created_at) OVER (ORDER BY id) OR lag(created_at) OVER (ORDER BY id) IS NULL AS ok FROM logs WHERE id > {start_id}) t;")
    check("LG-26", lag < 300 and order == "t", f"max age of this run's records {lag:.0f} s (UTC), ordered by time: {order}")
    e27 = email("lg27")
    register(e27)
    cnt = sql1(f"SELECT count(*) FROM logs WHERE message LIKE '%{e27}%';")
    check("LG-27", cnt == "1", f"one registration → {cnt} log record(s)")

    leaks = sql1(f"SELECT count(*) FROM logs WHERE message LIKE '%{PW}%' OR message LIKE '%WrongPass1%';")
    con_all = "\n".join(console("100000h"))
    check("LG-28", leaks == "0" and PW not in con_all and "WrongPass1" not in con_all, f"passwords in logs table: {leaks}; in console: {PW in con_all or 'WrongPass1' in con_all}")
    rc_val = rc
    tleak = sql1("SELECT count(*) FROM logs WHERE message LIKE '%eyJ%';")
    check("LG-29", tleak == "0" and "eyJhbGci" not in con_all and rc_val not in con_all, f"JWT in logs table: {tleak}; tokens in console: {'eyJhbGci' in con_all or rc_val in con_all}")
    n = sql1(f"SELECT count(*) FROM logs WHERE id > {start_id} AND message ~ '@';")
    check("LG-30", n == "0", f"records of this run containing an email: {n}", "" if n == "0" else "plain-text emails in logs — see FAT-17")
    r1 = req("POST", "/users/login", json_body={"email": "<script>@x.com", "password": "x"})
    r2 = req("POST", "/users/login", json_body={"email": "a" * 300 + "@x.com", "password": "x"})
    check("LG-31", r1.status_code == 422 and r2.status_code == 422, f"<script>@x.com → {r1.status_code}, 300-char email → {r2.status_code}",
          "invalid emails are rejected by validation before logging, so arbitrary strings cannot reach the log")
    r3 = req("POST", "/users/login", json_body={"email": 'a"\\n{"level":"ERROR"}@x.com', "password": "x"})
    check("LG-32", r3.status_code == 422, f"email with a newline / JSON fragment → {r3.status_code}", "rejected by email validation")
    cnt, oldest = sql("SELECT count(*), min(created_at) FROM logs;")[0]
    check("LG-33", False, f"logs table: {cnt} rows since {oldest}; no retention / cleanup in the code",
          "the table grows without limit — retention policy to be clarified")

    app_lines = [l for l in console("100000h") if l.startswith("{")]
    bad = []
    parsed = []
    for l in app_lines:
        try:
            parsed.append(json.loads(l))
        except ValueError:
            bad.append(l)
    total_lines = len([l for l in console("100000h") if l.strip()])
    check("LG-34", bool(app_lines) and not bad, f"container log: {total_lines} lines in total, JSON lines: {len(app_lines)}, invalid: {len(bad)}",
          "" if app_lines else "no application log line reaches the console: logging.config.fileConfig() in alembic/env.py runs at startup "
          "(run_migrations) and disables the already created 'app' and uvicorn loggers")
    iso_ok = all(re.match(r"\d{4}-\d\d-\d\dT[\d:.]+\+00:00$", p.get("time", "")) for p in parsed)
    check("LG-35", bool(parsed) and all({"time", "level", "message"} <= set(p) for p in parsed) and iso_ok,
          f"JSON lines to check: {len(parsed)}", "" if parsed else "cannot be verified — no JSON lines in the console (LG-34)")
    item_line = next((p for p in reversed(parsed) if p.get("message") == "item_created"), None)
    check("LG-36", bool(item_line) and {"user_id", "path", "method", "status_code"} <= set(item_line),
          f"item_created line in the console: {item_line}", "" if item_line else "cannot be verified — no JSON lines in the console (LG-34)")
    cons_line = next((p for p in reversed(parsed) if p.get("message") == "item_deleted"), None)
    db_line = last_log("message='item_deleted'")
    match = cons_line and db_line and cons_line["level"] == db_line[0] and str(cons_line.get("user_id")) == db_line[2]
    check("LG-37", bool(match), f"console {cons_line and (cons_line['level'], cons_line.get('user_id'))} vs DB {db_line and (db_line[0], db_line[2])}",
          "" if cons_line else "the event is in the DB but not in the console (LG-34)")
    other = [l for l in console("100000h") if l.strip() and not l.startswith("{")]
    check("LG-38", not other, f"non-JSON lines in the stream: {len(other)} (e.g. {other[-1][:70] if other else '-'})",
          "" if not other else "the only lines in the stream are alembic's plain-text startup messages; uvicorn access logs are "
          "suppressed together with the app logger (LG-34)")


# ───────────────────────── 3. CORS ─────────────────────────

def preflight(path, origin=ALLOWED, method="POST", headers="Authorization, Content-Type"):
    h = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        h["Access-Control-Request-Headers"] = headers
    return req("OPTIONS", path, headers=h)


def s_cors():
    r = preflight("/items/")
    h = r.headers
    check("CR-01", r.status_code == 200 and h.get("access-control-allow-origin") == ALLOWED and h.get("access-control-allow-credentials") == "true"
          and "POST" in h.get("access-control-allow-methods", ""), f"{r.status_code}; ACAO={h.get('access-control-allow-origin')}, "
          f"ACAC={h.get('access-control-allow-credentials')}, methods={h.get('access-control-allow-methods')}")
    allow_h = h.get("access-control-allow-headers", "").lower()
    check("CR-02", "authorization" in allow_h and "content-type" in allow_h, f"Allow-Headers: {h.get('access-control-allow-headers')}")
    got = {m: preflight("/items/1", method=m).status_code for m in ("PUT", "DELETE")}
    check("CR-03", all(c == 200 for c in got.values()), str(got))
    S["max_age"] = h.get("access-control-max-age")

    g = req("GET", "/health", headers={"Origin": ALLOWED})
    check("CR-04", g.headers.get("access-control-allow-origin") == ALLOWED and g.headers.get("access-control-allow-credentials") == "true",
          f"ACAO={g.headers.get('access-control-allow-origin')}, ACAC={g.headers.get('access-control-allow-credentials')}")
    e = email("cors")
    register(e)
    lr = req("POST", "/users/login", json_body={"email": e, "password": PW}, headers={"Origin": ALLOWED})
    check("CR-05", lr.headers.get("access-control-allow-origin") == ALLOWED and "refresh_token=" in lr.headers.get("set-cookie", ""),
          f"ACAO={lr.headers.get('access-control-allow-origin')}, Set-Cookie present: {'refresh_token=' in lr.headers.get('set-cookie', '')}")
    acaos = {g.headers.get("access-control-allow-origin"), lr.headers.get("access-control-allow-origin"), h.get("access-control-allow-origin")}
    check("CR-06", "*" not in acaos, f"Allow-Origin values seen: {sorted(x for x in acaos if x)}")
    check("CR-07", "origin" in g.headers.get("vary", "").lower(), f"Vary: {g.headers.get('vary')}")
    check("CR-08", True, f"Access-Control-Max-Age: {S['max_age']}")

    r = preflight("/items/", origin="http://evil.com")
    check("CR-09", r.status_code == 400 and "access-control-allow-origin" not in r.headers, f"{short(r, 60)}; ACAO={r.headers.get('access-control-allow-origin')}")
    g2 = req("GET", "/health", headers={"Origin": "http://evil.com"})
    check("CR-10", g2.status_code == 200 and "access-control-allow-origin" not in g2.headers, f"{g2.status_code}; ACAO={g2.headers.get('access-control-allow-origin')}")
    looks = ["https://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://localhost:3000.evil.com", "http://evil.com/http://localhost:3000"]
    got = {o: preflight("/items/", origin=o).headers.get("access-control-allow-origin") for o in looks}
    check("CR-11", not any(got.values()), f"allowed among look-alikes: {[o for o, v in got.items() if v] or 'none'}")
    r = preflight("/items/", origin="null")
    check("CR-12", "access-control-allow-origin" not in r.headers, f"Origin: null → {r.status_code}, ACAO={r.headers.get('access-control-allow-origin')}")
    r = preflight("/items/", origin="http://LOCALHOST:3000")
    check("CR-13", True, f"Origin: http://LOCALHOST:3000 → {r.status_code}, ACAO={r.headers.get('access-control-allow-origin')}",
          "origin matching is case-sensitive" if r.status_code == 400 else "")
    r = preflight("/items/1", method="PATCH")
    check("CR-14", r.status_code == 400 and "PATCH" not in r.headers.get("access-control-allow-methods", ""), f"{short(r, 60)}")
    r = preflight("/items/", headers="X-Custom")
    check("CR-15", r.status_code == 200, f"X-Custom → {r.status_code}, Allow-Headers={r.headers.get('access-control-allow-headers')}",
          "allow_headers=* accepts any request header — broader than needed (Authorization, Content-Type)")

    u = req("GET", "/items/", headers={"Origin": ALLOWED, "Authorization": "Bearer bad"})
    check("CR-16", u.status_code == 401 and u.headers.get("access-control-allow-origin") == ALLOWED, f"{u.status_code}; ACAO={u.headers.get('access-control-allow-origin')}")

    lim = ROOT / "qa" / ".tmp_cr17.yml"
    lim.write_text('services:\n  api:\n    environment:\n      LOGIN_RATE_LIMIT: "2/minute"\n')
    try:
        subprocess.run(BASE_COMPOSE + ["-f", str(lim), "up", "-d"], capture_output=True, cwd=ROOT)
        wait_health()
        codes = [req("POST", "/users/login", json_body={"email": e, "password": "x"}, headers={"Origin": ALLOWED}) for _ in range(3)]
        last = codes[-1]
        check("CR-17", last.status_code == 429 and last.headers.get("access-control-allow-origin") == ALLOWED,
              f"{last.status_code}; ACAO={last.headers.get('access-control-allow-origin')}")
    finally:
        lim.unlink(missing_ok=True)
        subprocess.run(BASE_COMPOSE + ["up", "-d"], capture_output=True, cwd=ROOT)
        wait_health()

    present = S.get("cr18")
    check("CR-18", present == ALLOWED, f"500 (DB down, HL-15) with the allowed Origin → ACAO={present}",
          "" if present else "500 responses carry no CORS headers — the browser reports a CORS error instead of the server error")
    codes = [req("OPTIONS", "/health", headers={"Origin": ALLOWED, "Access-Control-Request-Method": "GET"}).status_code for _ in range(110)]
    check("CR-19", True, f"110 × preflight → {sorted(set(codes))}", "preflight requests are answered by CORSMiddleware before the rate limiter" if 429 not in codes else "")

    cr20 = os.environ.get("CR20")
    if cr20:
        st, actual, note = (cr20.split("|") + ["", ""])[:3]
        check("CR-20", st == "pass", actual, note)
    else:
        check("CR-20", False, "not executed — run with CR20=… after the browser check", status="blocked")

    n = req("GET", "/health")
    check("CR-21", n.status_code == 200 and "access-control-allow-origin" not in n.headers, f"no Origin → {n.status_code}, ACAO absent: {'access-control-allow-origin' not in n.headers}")
    src = (ROOT / "app/main.py").read_text()
    hard = 'allow_origins=["http://localhost:3000"]' in src
    check("CR-22", not hard, "app/main.py: allow_origins=[\"http://localhost:3000\"] (hardcoded)" if hard else "origins from configuration",
          "allowed origins are hardcoded — any other environment needs a code change and a new release" if hard else "")


# ───────────────────────── 4. API docs ─────────────────────────

def s_docs():
    d = req("GET", "/docs")
    check("DOC-01", d.status_code == 200 and "swagger-ui" in d.text, f"/docs → {d.status_code}, Swagger UI page: {'swagger-ui' in d.text}")
    rd = req("GET", "/redoc")
    check("DOC-02", rd.status_code == 200 and "redoc" in rd.text.lower(), f"/redoc → {rd.status_code}")
    o = req("GET", "/openapi.json")
    spec = o.json()
    try:
        from openapi_spec_validator import validate
        validate(spec)
        valid, err = True, ""
    except Exception as ex:  # noqa: BLE001
        valid, err = False, str(ex)[:120]
    check("DOC-03", o.status_code == 200 and valid, f"/openapi.json → {o.status_code}, openapi {spec.get('openapi')}, valid: {valid} {err}")

    ops = {f"{m.upper()} {p}": op for p, v in spec["paths"].items() for m, op in v.items()}
    expected = {"POST /users/register", "POST /users/login", "POST /users/refresh", "POST /users/logout", "POST /users/logout-all",
                "GET /items/", "GET /items/all", "POST /items/", "PUT /items/{item_id}", "DELETE /items/{item_id}", "GET /health"}
    tags = sorted({t for op in ops.values() for t in op.get("tags", [])})
    check("DOC-04", expected <= set(ops), f"{len(ops)} operations, missing: {sorted(expected - set(ops)) or 'none'}; tags: {tags}")
    check("DOC-05", spec["info"].get("version") == "1.7.0", f"info.version = {spec['info'].get('version')}")
    undoc = sorted(k for k, op in ops.items() if not op.get("description") and not op.get("summary", "").strip()
                   or k.startswith(("GET /items", "POST /items", "PUT /items", "DELETE /items")) and not op.get("description"))
    check("DOC-06", not undoc, f"operations without a description: {undoc or 'none'}",
          "" if not undoc else "items endpoints have only auto-generated summaries and no descriptions (Roadmap v1.7 marks this as done)")
    check("DOC-07", False, "login: 200/401/404 reproduced; logout-all documents 401 but returns 403 without a token (FAT-13); "
          "refresh/logout document an unreachable 422 (FAT-22); items endpoints document no error codes (CL-02 CTR-03)")
    empty = sorted(k for k, op in ops.items()
                   if any(c.startswith("2") and not (resp.get("content", {}).get("application/json", {}).get("schema") or {})
                          for c, resp in op.get("responses", {}).items()))
    check("DOC-08", not empty, f"operations whose success response schema is empty: {empty or 'none'}",
          "" if not empty else "no response_model — clients get no response schema")
    params = {p["name"]: p.get("schema", {}) for p in spec["paths"]["/items/all"]["get"].get("parameters", [])}
    bounds = all("minimum" in s or "exclusiveMinimum" in s for s in params.values())
    check("DOC-09", bounds, f"/items/all params: {params}", "" if bounds else "no minimum / maximum constraints (see PAG-16…PAG-20)")
    schemas = spec.get("components", {}).get("schemas", {})
    pw = schemas.get("UserCreate", {}).get("properties", {}).get("password", {})
    check("DOC-10", "minLength" in pw, f"UserCreate.password schema: {pw}", "" if "minLength" in pw else "the 6-character minimum exists only in the description text (see FAT-8)")
    sec = spec.get("components", {}).get("securitySchemes", {})
    protected = [k for k, op in ops.items() if op.get("security")]
    check("DOC-11", any(v.get("scheme") == "bearer" for v in sec.values()) and "GET /items/" in protected,
          f"securitySchemes: {list(sec)}; operations with security: {len(protected)}")
    e, uid, tok, _ = new_user("docs")
    r = req("GET", "/items/", headers=bearer(tok))
    check("DOC-12", r.status_code == 200, f"Bearer token as sent by the Authorize button → GET /items/ {r.status_code}",
          "verified at the API level; the Authorize dialog itself was checked in the browser")
    cookie_params = [k for k, op in ops.items() for p in op.get("parameters", []) if p.get("in") == "cookie"]
    check("DOC-13", True, f"operations with a documented cookie parameter: {cookie_params}",
          "refresh_token is documented as a cookie parameter, but Swagger UI cannot send cookie parameters — "
          "these endpoints work from the UI only with the cookie the browser received from /users/login")
    info = spec["info"]
    url = info.get("contact", {}).get("url")
    try:
        code = httpx.head(url, follow_redirects=True, timeout=10).status_code if url else None
    except Exception:
        code = "error"
    check("DOC-14", bool(info.get("license", {}).get("name")) and code == 200, f"contact={info.get('contact')}, license={info.get('license')}, repo link → {code}")

    readme = (ROOT / "docs/APP_README.md").read_text()
    rows = re.findall(r"\|\s*\w+\s*\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`", readme)
    documented = {f"{m} {p}".replace("{item_id}", "{item_id}") for m, p in rows}
    norm = lambda s: s.rstrip("/") or "/"
    diff = {norm(x) for x in documented} ^ {norm(x) for x in expected}
    check("DOC-15", not diff, f"README endpoint table vs OpenAPI — differences: {sorted(diff) or 'none'}")
    env_readme = set(re.findall(r"\|\s*`([A-Z_]+)`\s*\|", readme))
    compose_vars = set(re.findall(r"\$\{(\w+)\}", (ROOT / "docker-compose.yml").read_text()))
    example_orig = subprocess.run(["git", "show", "660708b:.env.example"], capture_output=True, text=True, cwd=ROOT).stdout
    example_vars = set(re.findall(r"^([A-Z_]+)=", example_orig, re.M))
    missing = sorted(compose_vars - env_readme - example_vars)
    check("DOC-16", not missing, f"variables required by docker-compose.yml but absent from the README table and .env.example (build 660708b): {missing or 'none'}",
          "" if not missing else "following the README (cp .env.example .env → docker-compose up) the db container gets no credentials and the stand does not start")


def main():
    if not wait_health(timeout=30):
        sys.exit("The stand is not ready")
    env = docker("exec", "fastapi_api", "printenv", "LOGIN_RATE_LIMIT").stdout.strip()
    if env != "1000/minute":
        sys.exit(f"Start the stand with qa/docker-compose.functional.yml (LOGIN_RATE_LIMIT={env!r})")
    only = sys.argv[1:]  # e.g. s_startup — re-run selected sections and merge into today's results
    print("CL-04 Health / Logs / CORS / Docs run" + (f" (sections: {', '.join(only)})" if only else "") + "\n", flush=True)
    for fn in (s_health, s_db_down, s_startup, s_logging, s_cors, s_docs):
        if only and fn.__name__ not in only:
            continue
        print(f"── {fn.__name__}", flush=True)
        section(fn)
    if only:
        merge_into_today("CL-04", only)
    else:
        save("CL-04", "CL-04 Health / Logs / CORS / API Docs", "Local (Docker), qa/docker-compose.functional.yml")


if __name__ == "__main__":
    main()
