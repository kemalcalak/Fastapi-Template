# CLAUDE.md

## Commands

### Run
```bash
docker-compose up -d --build
```

### Test
```bash
uv run pytest
uv run pytest -v
uv run pytest --cov=app
uv run pytest app/tests/test_users.py
```

### Lint & Format
```bash
uv run ruff format .
uv run ruff check --fix .
```

### Migrations
```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
uv run alembic downgrade -1
uv run alembic history
```

### Dependencies
```bash
uv add <package>
uv add --dev <package>
uv sync
```

---

## Environment Setup

1. Copy `.env.example` → `.env`
2. Python >= 3.12 required (see `.python-version`)
3. Use `uv` only — never `pip`
4. Start DB first:

```bash
docker-compose up -d db
```

API: `http://localhost:8000`  
Swagger: `http://localhost:8000/docs`

### Required ENV

| Variable | Default | Description |
|---|---|---|
| `PROJECT_NAME` | `FastAPI Template` | Project display name |
| `SECRET_KEY` | — | Long random string, never hardcode |
| `ENVIRONMENT` | `local` | `local`, `development`, or `production` |
| `POSTGRES_SERVER` | `localhost` | PostgreSQL host |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | — | PostgreSQL password |
| `POSTGRES_DB` | `app` | PostgreSQL database name |
| `FIRST_SUPERUSER` | `admin@example.com` | Initial admin email |
| `FIRST_SUPERUSER_PASSWORD` | — | Initial admin password |
| `CLOUDINARY_CLOUD_NAME` | — | Cloudinary cloud name (required for `POST /upload`) |
| `CLOUDINARY_API_KEY` | — | Cloudinary API key (required for `POST /upload`) |
| `CLOUDINARY_API_SECRET` | — | Cloudinary API secret (required for `POST /upload`) |
| `CLOUDINARY_UPLOAD_FOLDER` | `uploads` | Cloudinary folder uploads are stored under |

> Never commit `.env`. It is already in `.gitignore`.

---

## Architecture

Strict layered structure — dependency flow is one-directional:

```
api → services → repositories → models
```

### Responsibilities

- `api/routes/` → Routing only. Uses `Depends()` for session and current user. No business logic.
- `api/dependencies/` → Shared FastAPI dependencies (`get_session`, `get_current_user`, etc.).
- `services/` → All business logic. Receives session as argument. May raise `HTTPException` directly.
- `repositories/` → All DB queries. No business rules. Receives session as argument.
- `models/` → SQLAlchemy ORM definitions only. No logic.
- `schemas/` → Pydantic DTOs. Separate `Create`, `Update`, `Response` per domain.
- `core/` → Config, JWT auth, bcrypt, exceptions, logging.
- `utils/` → Pure helper functions shared across layers.

---

## Hard Rules

These are non-negotiable:

- No classes for repositories or services — use pure async functions
- `Depends()` is used only in route handlers, never in service or repository functions
- `api/routes/` never calls repositories directly — always goes through `services/`
- Services never call other services — use shared repository functions or `use_cases/` instead
- No sync DB calls — all queries must be `async/await`
- No raw ORM objects returned from endpoints — always map to Pydantic schemas
- No secrets in code — always use `pydantic-settings` and `.env`
- Error messages must ALWAYS come from `app/core/messages/error_message.py`
- Success messages must ALWAYS come from `app/core/messages/success_message.py`
- Never hardcode error or success strings inline (e.g., `detail="User not found"`)
- Always create an Alembic migration after changing a model
- Always commit `uv.lock` together with dependency changes
- Never use `pip install` — use `uv add` only
- All functions must have a docstring — minimum one line, always in English

---

## Error Handling & Logging

- `HTTPException` can be raised in both services and route handlers
- Use guard clauses at the top of functions — fail fast, happy path last
- Register global handlers in `app/main.py` for unexpected errors
- Never expose internal errors or stack traces to clients
- All services must log critical failures
- Use structured logging (JSON format in production)
- Error messages must ALWAYS be retrieved from `app/core/messages/error_message.py`
- Success messages must ALWAYS be retrieved from `app/core/messages/success_message.py`
- Never hardcode error or success strings (e.g., do not write `detail="User not found"`)

---

## Authentication & Security

- All JWT logic lives in `app/core/security.py`
- Protect routes with `Depends(get_current_user)` defined in `app/api/dependencies/`
- Always hash passwords with `bcrypt` — never store or log plain-text passwords
- Rate limiting is handled via `slowapi` — configure in `app/core/`
- First superuser is seeded automatically on startup using `FIRST_SUPERUSER` and `FIRST_SUPERUSER_PASSWORD`

---

## Git Workflow

### Branches

- `main` → production
- `develop` → staging
- `feature/*` → new features
- `fix/*` → bugfix

### Commits

Use conventional commits:

```
feat: add user activity log
fix: prevent duplicate email registration
refactor: optimize repository queries
chore: update dependencies
```

---

## AI Usage Rules

- Follow the layered architecture strictly — never bypass the service layer
- Never generate classes for services or repositories — use pure async functions
- Never place `Depends()` inside service or repository functions
- Never generate sync DB code — always `async/await`
- Never hardcode error/success message strings — always import from `core/messages/`
- Always write a docstring for every function — minimum one line, in English
- Never ignore Hard Rules above
- Prefer small, incremental changes over large rewrites
- Always include tests when adding new logic
- When adding a new domain, create all layers: model → schema → repository → service → route
- Always generate an Alembic migration when touching `models/`

---

## CI/CD

GitHub Actions runs on every push:

- `uv run ruff check .`
- `uv run pytest`
- Docker build check

All checks must pass before merge.