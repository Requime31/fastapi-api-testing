# FastAPI API Testing — QA-проект

Ручное и исследовательское тестирование REST API на **FastAPI + PostgreSQL** с JWT-аутентификацией, refresh-токенами, rate limiting и soft delete.

Проект имитирует работу QA Engineer на реальном бэкенде: от smoke-тестирования и тест-плана до чек-листов, баг-репортов и итогового отчёта.

> Тестируемое приложение написано [nisanMan](https://github.com/nisanMan) — оригинальный репозиторий [nisanMan/fastapi-project](https://github.com/nisanMan/fastapi-project). История коммитов автора сохранена. QA-артефакты в папках `docs/`, `postman/` и в [Issues](../../issues) — моя работа.

---

## Статус

| Этап | Артефакт | Статус |
|---|---|---|
| Smoke-тестирование | — | ✅ Выполнено |
| Планирование | [Test Plan](docs/TEST_PLAN.md) | ✅ Готов |
| Тест-дизайн | [Чек-листы](docs/checklists/) — 381 проверка | ✅ Готовы |
| Выполнение | Прогон чек-листов, Postman-коллекция | ⏳ В процессе |
| Трекинг | Jira `FAT` ([эпик цикла FAT-1](../../issues/1)) → зеркало в [Issues](../../issues) | 🔄 Задачи цикла заведены |
| Отчётность | Test Summary Report | ⏳ |

---

## QA-артефакты

### [Test Plan](docs/TEST_PLAN.md)
Скоуп (15 функций), стратегия, уровни и виды тестирования, техники тест-дизайна, 15 зон риска, окружение, entry / exit criteria, severity и жизненный цикл дефекта, график, риски проекта.

### Чек-листы

| Чек-лист | Модуль | Проверок |
|---|---|---|
| [CL-01 Auth](docs/checklists/CL-01_Auth.md) | Регистрация, логин, refresh, logout, logout-all, безопасность токенов | 118 |
| [CL-02 Items](docs/checklists/CL-02_Items.md) | CRUD, пагинация, soft delete, разграничение доступа (IDOR) | 117 |
| [CL-03 Rate Limit](docs/checklists/CL-03_RateLimit.md) | Лимиты, формат `429`, окно сброса, независимость счётчиков, попытки обхода | 50 |
| [CL-04 Health / Logs / CORS / Docs](docs/checklists/CL-04_Health_Logs_CORS.md) | Health check и отказ БД, логирование, CORS, OpenAPI | 96 |
| **Всего** | | **381** |

### Применённые техники тест-дизайна
- классы эквивалентности и граничные значения — валидация полей, пагинация, лимиты;
- таблица принятия решений — права на операции с чужими / удалёнными / несуществующими items;
- диаграмма состояний — жизненный цикл refresh-токена (выдан → ротирован / отозван / истёк);
- error guessing на основе анализа исходного кода.

### Postman
Коллекция `FastAPI Project - QA Testing` и environment `Fast API Local` — в папке [`postman/`](postman/), в формате Postman Local View (подключается через Postman → Workspace → Local View, файл [`.postman/resources.yaml`](.postman/resources.yaml)).

### Трекинг: Jira + GitHub Issues
Работа ведётся в **Jira** (проект `FAT`), как на реальном проекте: баги с полями Severity / Priority / Components / Affects version, задачи на прогон чек-листов, вопросы к разработчику, workflow `К выполнению → В работе → Исправлено → Повторная проверка → Готово`.

Jira закрыта для посторонних, поэтому каждая задача зеркалируется в [Issues](../../issues) этого репозитория с тем же ключом в заголовке (`[FAT-12] ...`), метками `bug` / `task` / `question`, `severity:*`, `component:*` и milestone тестового цикла. Схема синхронизации — в [Test Plan, раздел 7.4](docs/TEST_PLAN.md#74-трекинг-jira--github-issues).

| Что посмотреть | Ссылка |
|---|---|
| Все баги | [label:bug](../../issues?q=label%3Abug) |
| Открытые Critical / Blocker | [severity:critical, severity:blocker](../../issues?q=is%3Aopen+label%3Aseverity%3Acritical%2Cseverity%3Ablocker) |
| Задачи на прогон | [label:task](../../issues?q=label%3Atask) |
| Вопросы к разработчику | [label:question](../../issues?q=label%3Aquestion) |
| Ход тестового цикла | [Milestones](../../milestones) |

---

## Тестируемое приложение

| | |
|---|---|
| Стек | Python 3.11, FastAPI, SQLAlchemy, PostgreSQL 15, Alembic, slowapi, Docker Compose |
| Аутентификация | JWT access token (30 мин) + refresh token в httpOnly cookie (7 дней) с ротацией |
| Эндпоинты | `/users/register`, `/users/login`, `/users/refresh`, `/users/logout`, `/users/logout-all`, `/items/` (CRUD), `/items/all` (пагинация), `/health` |
| Тестируемая версия | API v1.7.0, коммит `660708b` |
| Описание от автора | [docs/APP_README.md](docs/APP_README.md) |

---

## Как поднять стенд

Требуется Docker и Docker Compose.

```bash
git clone https://github.com/Requime31/fastapi-api-testing.git
cd fastapi-api-testing
cp .env.example .env
docker-compose up --build
```

| | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

Для функционального тестирования поднимите лимиты в `.env` до `1000/minute`. Rate limit проверяется отдельно, с лимитами по умолчанию — см. [CL-03](docs/checklists/CL-03_RateLimit.md).

Доступ к БД для проверки данных:

```bash
docker exec -it fastapi_postgres psql -U postgres -d fastapi_db
```

Автотесты разработчика (pytest, SQLite):

```bash
docker-compose run api pytest tests/ -v
```

---

## Инструменты

Jira · Postman · Swagger UI · psql · Docker Compose · curl · jwt.io · pytest · GitHub Issues

---

## Структура репозитория

```
├── docs/
│   ├── TEST_PLAN.md          # тест-план
│   ├── checklists/           # чек-листы CL-01…CL-04
│   └── APP_README.md         # описание приложения от автора
├── postman/                  # Postman-коллекция и environment
├── .github/
│   ├── ISSUE_TEMPLATE/       # шаблон баг-репорта
│   └── workflows/ci.yml      # автотесты разработчика в CI
├── app/                      # тестируемое приложение
└── tests/                    # автотесты разработчика (pytest)
```
