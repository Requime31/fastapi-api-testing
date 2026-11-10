"""Shared helpers for checklist run scripts (CL-02 … CL-04)."""
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
PW = "Passw0rd!"
RUN_ID = datetime.now().strftime("%m%d%H%M%S")
OUT_DIR = Path(__file__).resolve().parents[1] / "runs"
APP_BUILD = "660708b"

client = httpx.Client(base_url=BASE, timeout=30)  # no cookie jar, no redirects
results: dict[str, dict] = {}
timings: dict[str, list[float]] = {}


def email(tag: str) -> str:
    return f"qa{RUN_ID}_{tag}@test.com"


def req(method, path, *, json_body=None, content=None, headers=None, cookie=None, params=None):
    h = dict(headers or {})
    if cookie is not None:
        h["Cookie"] = f"refresh_token={cookie}"
    t0 = time.perf_counter()
    if content is not None:
        r = client.request(method, path, content=content, headers=h, params=params)
    else:
        r = client.request(method, path, json=json_body, headers=h, params=params)
    timings.setdefault(f"{method} {path.split('?')[0]}", []).append((time.perf_counter() - t0) * 1000)
    return r


def body(r):
    try:
        return r.json()
    except Exception:
        return r.text[:300]


def short(r, n=200):
    b = body(r)
    s = json.dumps(b, ensure_ascii=False) if not isinstance(b, str) else b
    return f"{r.status_code} {s[:n]}"


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def refresh_cookie(r):
    for c in r.headers.get_list("set-cookie"):
        if c.startswith("refresh_token="):
            return c.split(";", 1)[0].split("=", 1)[1].strip('"')
    return None


def sql(q: str) -> list[list[str]]:
    p = subprocess.run(
        ["docker", "exec", "-i", "fastapi_postgres", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F "|" -v ON_ERROR_STOP=1'],
        input=q, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return [line.split("|") for line in p.stdout.strip().splitlines() if line]


def sql1(q: str) -> str | None:
    rows = sql(q)
    return rows[0][0] if rows else None


def register(e, pw=PW, **extra):
    return req("POST", "/users/register", json_body={"email": e, "password": pw, **extra})


def login(e, pw=PW):
    r = req("POST", "/users/login", json_body={"email": e, "password": pw})
    tok = body(r).get("access_token") if r.status_code == 200 else None
    return r, tok, refresh_cookie(r)


def new_user(tag):
    """Registers and logs in a user; returns (email, user_id, access_token, refresh_cookie)."""
    e = email(tag)
    register(e)
    _, tok, rc = login(e)
    return e, int(sql1(f"SELECT id FROM users WHERE email='{e}';")), tok, rc


def mask(s: str) -> str:
    """Removes tokens from stored results (the repository is public)."""
    s = re.sub(r"eyJ[\w-]*(\.[\w-]*){0,2}", "<jwt>", s)
    return re.sub(r"refresh_token=[\w-]{6,}…?", "refresh_token=<redacted>", s)


def check(cid, ok, actual, note="", status=None):
    actual = mask(str(actual))
    st = status or ("pass" if ok else "fail")
    results[cid] = {"status": st, "actual": actual, "note": note}
    mark = {"pass": "✅", "fail": "❌", "blocked": "⚠️", "skip": "⏭"}[st]
    print(f"{mark} {cid}: {actual}" + (f"  — {note}" if note else ""), flush=True)


def section(fn):
    try:
        fn()
    except Exception as ex:  # noqa: BLE001
        print(f"⚠️ section {fn.__name__} aborted: {ex!r}", flush=True)
        results[f"_error_{fn.__name__}"] = {"status": "blocked", "actual": repr(ex), "note": ""}


def health_ok():
    return client.get("/health").json() == {"status": "ok", "database": "ok"}


def save(checklist_id: str, title: str, environment: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{checklist_id}_{datetime.now():%Y-%m-%d}.json"
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out.write_text(json.dumps({
        "checklist": title, "run_id": RUN_ID, "date": datetime.now(timezone.utc).isoformat(),
        "environment": environment, "app_build": APP_BUILD, "repo_commit": commit, "results": results,
    }, ensure_ascii=False, indent=2))
    counts = {}
    for v in results.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(f"\nTotal: {counts}; saved to {out}")


def merge_into_today(checklist_id: str, sections: list[str]):
    """Merges the results of re-run sections into today's results file (existing checks are replaced in place)."""
    path = OUT_DIR / f"{checklist_id}_{datetime.now():%Y-%m-%d}.json"
    data = json.loads(path.read_text())
    merged = {k: v for k, v in data["results"].items() if not k.startswith("_error_")}
    merged.update(results)
    data["results"] = merged
    data.setdefault("reruns", []).append({"run_id": RUN_ID, "sections": sections, "checks": sorted(results)})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    counts = {}
    for v in merged.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(f"\nMerged into {path}: {counts}")
