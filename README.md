# FastAPI API Testing — QA Project

Manual and exploratory testing of a **FastAPI + PostgreSQL** REST API with JWT authentication, refresh tokens, rate limiting and soft delete.

The project simulates the work of a QA Engineer on a real backend: from smoke testing and a test plan to checklists, bug reports and a test summary report.

> The application under test was written by [nisanMan](https://github.com/nisanMan) — original repository: [nisanMan/fastapi-project](https://github.com/nisanMan/fastapi-project). The author's commit history is preserved. The QA artifacts in `docs/`, `qa/`, `postman/` and [Issues](../../issues) are my work.

---

## Status

| Stage | Artifact | Status |
|---|---|---|
| Smoke testing | — | ✅ Done |
| Planning | [Test Plan](docs/TEST_PLAN.md) | ✅ Ready |
| Test design | [Checklists](docs/checklists/) — 381 checks | ✅ Ready |
| Execution | All 4 checklists executed on build `660708b` — 381 checks: 300 ✅ / 79 ❌ / 2 ⏭ ([CL-01](docs/checklists/CL-01_Auth.md) 98/19/1 · [CL-02](docs/checklists/CL-02_Items.md) 97/19/1 · [CL-03](docs/checklists/CL-03_RateLimit.md) 38/12/0 · [CL-04](docs/checklists/CL-04_Health_Logs_CORS.md) 67/29/0; [raw results](qa/runs/)) | ✅ Cycle 1 executed |
| Tracking | Jira `FAT` ([cycle epic FAT-1](../../issues/1)) → mirrored to [Issues](../../issues): [33 bugs](../../issues?q=label%3Abug) (11 Major · 20 Minor · 2 Trivial, no Blocker / Critical) and [10 questions](../../issues?q=label%3Aquestion) filed, every one linked from its checklist | ✅ Filed |
| Reporting | [Test Summary Report — cycle 1](docs/reports/TSR_cycle1_v1.7.0.md): pass rate 79.2%, 11 Major open — v1.7.0 not ready for release | ✅ Cycle 1 closed |
| Fix verification | Cycle 2 on build `v1.7.1`: 5 fixes in PRs [#51](../../pull/51)–[#56](../../pull/56) with unit tests (29 → 42); re-test 24 ✅ / 1 ❌ — 4 bugs closed, [FAT-9](../../issues/9) reopened; regression CL-01 83.8% → 90.6%, CL-02 unchanged, no new failures | ✅ Cycle 2 closed |
| Reporting | [Test Summary Report — cycle 2](docs/reports/TSR_cycle2_v1.7.1.md): pass rate 81.3%, 10 Major open — v1.7.1 not ready for release | ✅ |

---

## QA artifacts

### [Test Plan](docs/TEST_PLAN.md)
Scope (15 features), strategy, test levels and types, test design techniques, 15 risk areas, environment, entry / exit criteria, severity and defect lifecycle, schedule, project risks.

### Checklists

| Checklist | Module | Checks |
|---|---|---|
| [CL-01 Auth](docs/checklists/CL-01_Auth.md) | Registration, login, refresh, logout, logout-all, token security | 118 |
| [CL-02 Items](docs/checklists/CL-02_Items.md) | CRUD, pagination, soft delete, access control (IDOR) | 117 |
| [CL-03 Rate Limit](docs/checklists/CL-03_RateLimit.md) | Limits, `429` format, reset window, counter independence, bypass attempts | 50 |
| [CL-04 Health / Logs / CORS / Docs](docs/checklists/CL-04_Health_Logs_CORS.md) | Health check and DB failure, logging, CORS, OpenAPI | 96 |
| **Total** | | **381** |

### Test design techniques used
- equivalence partitioning and boundary values — field validation, pagination, limits;
- decision table — permissions on other users' / deleted / non-existent items;
- state transition — refresh token lifecycle (issued → rotated / revoked / expired);
- error guessing based on source code analysis.

### Checklist execution
Each checklist is executed by a script in [`qa/scripts/`](qa/scripts/): every check is an HTTP request to the local stand, database state is verified with `psql` inside the container. Raw results are stored in [`qa/runs/`](qa/runs/) and transferred to the checklist (status, actual result, linked bug).

### Postman
Collection `FastAPI Project - QA Testing` and environment `Fast API Local` live in [`postman/`](postman/) in Postman Local View format (open via Postman → Workspace → Local View, file [`.postman/resources.yaml`](.postman/resources.yaml)).

### Tracking: Jira + GitHub Issues
Work is tracked in **Jira** (project `FAT`) as on a real project: bugs with Severity / Priority, components and affected version, checklist run tasks, questions to the developer, and a defect workflow `To Do → In Progress → Fixed → Re-test → Done`.

Jira is private, so every Jira issue is mirrored to this repository's [Issues](../../issues) with the same number (`FAT-12` ↔ `#12`), labels `bug` / `task` / `question`, `severity:*`, `component:*` and the test cycle milestone. Jira is kept in Russian; the GitHub mirror is an English translation. Sync rules: [Test Plan, section 7.4](docs/TEST_PLAN.md#74-tracking-jira--github-issues).

| What to look at | Link |
|---|---|
| All bugs | [label:bug](../../issues?q=label%3Abug) |
| Open Critical / Blocker | [severity:critical, severity:blocker](../../issues?q=is%3Aopen+label%3Aseverity%3Acritical%2Cseverity%3Ablocker) |
| Run tasks | [label:task](../../issues?q=label%3Atask) |
| Questions to the developer | [label:question](../../issues?q=label%3Aquestion) |
| Test cycle progress | [Milestones](../../milestones) |

---

## Application under test

| | |
|---|---|
| Stack | Python 3.11, FastAPI, SQLAlchemy, PostgreSQL 15, Alembic, slowapi, Docker Compose |
| Authentication | JWT access token (30 min) + refresh token in an httpOnly cookie (7 days) with rotation |
| Endpoints | `/users/register`, `/users/login`, `/users/refresh`, `/users/logout`, `/users/logout-all`, `/items/` (CRUD), `/items/all` (pagination), `/health` |
| Version under test | Cycle 1: API v1.7.0, commit `660708b` · Cycle 2: API v1.7.1, tag `v1.7.1` (`5784850`) |
| Author's description | [docs/APP_README.md](docs/APP_README.md) |

---

## Running the stand

Requires Docker and Docker Compose.

```bash
git clone https://github.com/Requime31/fastapi-api-testing.git
cd fastapi-api-testing
cp .env.example .env
docker compose -f docker-compose.yml -f qa/docker-compose.functional.yml up -d --build
```

| | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

The `qa/docker-compose.functional.yml` override raises rate limits to `1000/minute` for functional checklists. Rate limiting itself is tested separately with default limits — start without the override, see [CL-03](docs/checklists/CL-03_RateLimit.md).

Run a checklist:

```bash
pip install httpx python-jose
python qa/scripts/run_cl01_auth.py
```

Database access for data checks:

```bash
docker exec -it fastapi_postgres psql -U postgres -d fastapi_db
```

Developer unit tests (pytest, SQLite):

```bash
docker compose run api pytest tests/ -v
```

---

## Tools

Jira · Postman · Swagger UI · psql · Docker Compose · curl · httpx · jwt.io · pytest · GitHub Issues

---

## Repository structure

```
├── docs/
│   ├── TEST_PLAN.md          # test plan
│   ├── checklists/           # checklists CL-01…CL-04 with run results
│   ├── reports/              # test summary reports per cycle
│   └── APP_README.md         # author's description of the application
├── qa/
│   ├── scripts/              # checklist execution scripts
│   ├── runs/                 # raw run results (JSON)
│   └── docker-compose.functional.yml  # stand override for functional testing
├── postman/                  # Postman collection and environment
├── .github/
│   ├── ISSUE_TEMPLATE/       # bug report and task templates
│   └── workflows/ci.yml      # developer unit tests in CI
├── app/                      # application under test
└── tests/                    # developer unit tests (pytest)
```
