# FastAPI Layered Architecture Template

A modern, production-ready FastAPI template utilizing a clean, layered (hexagonal-style) architecture. This template is designed for building robust and scalable backend services with clear separation of concerns, easy testing, and high maintainability.

## Features

- **Layered Architecture:** Strict separation between API logic, services, repositories, and data models.
- **Dependency Injection:** Fully utilizes FastAPI's dependency injection system.
- **Asynchronous Database:** `SQLAlchemy` with `asyncpg` for non-blocking database operations.
- **Database Migrations:** Pre-configured `Alembic` for schema version control.
- **Authentication & Security:** JWT validation and secure password hashing using `bcrypt` and `pyjwt`.
- **Environment Management:** Structured configuration via `pydantic-settings`.
- **Package Management via `uv`:** Extremely fast dependency resolution and environment management.
- **Testing:** Comprehensive test suite setup utilizing `pytest` and `pytest-asyncio`.
- **Code Quality:** `ruff` configuration for blazing-fast linting and formatting.
- **Docker Ready:** Includes `Dockerfile` and `docker-compose.yaml` for containerized deployments and local Postgres dev environment.

## Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **ORM:** [SQLAlchemy](https://www.sqlalchemy.org/)
- **Database Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Driver:** `asyncpg` (for PostgreSQL)
- **Validation:** [Pydantic v2](https://docs.pydantic.dev/latest/)
- **Linter & Formatter:** [Ruff](https://docs.astral.sh/ruff/)
- **Testing:** `pytest` + `pytest-asyncio`
- **Error Tracking:** Sentry SDK
- **Package Manager:** `uv`

## Project Structure

```bash
├── app/
│   ├── alembic/          # Database migration configurations
│   ├── api/              # API Layer: FastAPI routers and route handlers
│   ├── core/             # Core configurations, security, exceptions, logging
│   ├── models/           # Domain Layer: SQLAlchemy definitions
│   ├── repositories/     # Data Layer: Database operations and queries
│   ├── schemas/          # API Layer: Pydantic request/response schemas
│   ├── services/         # Business Logic Layer: Core use cases and orchestration
│   ├── tests/            # Test suite (integration and unit tests)
│   ├── utils/            # Helper functions and shared utilities
│   └── main.py           # Application entry point
├── alembic.ini           # Alembic settings
├── docker-compose.yaml   # Docker compose configuration (e.g., PostgreSQL DB)
├── Dockerfile            # Dockerfile for backend container
├── pyproject.toml        # Project dependencies and tool configurations
├── pytest.ini            # Pytest settings
└── uv.lock               # Dependency lock file
```

## Setup & Local Development

### Prerequisites

- Python >= 3.12
- Docker & Docker Compose (for local database)
- `uv` package manager (recommended)

### 1. Clone the Repository

Clone the repository to your local machine:

```bash
git clone https://github.com/kemalcalak/fastapi-template.git
cd fastapi-template
```

### 2. Environment Variables

Create a `.env` file from the provided template:

```bash
cp .env.example .env
```
Ensure you have set the required environment variables.

### 3. Start the Application via Docker

This project provides a `docker-compose.yaml` to spin up the entire stack, including the backend service and a local PostgreSQL instance:

```bash
docker-compose up -d --build
```

The API will be available at `http://localhost:8000`. You can test the endpoints via the Swagger UI available at `http://localhost:8000/docs`.

### 4. Run Migrations

To generate and apply the database tables using Alembic, run the migration command inside the backend container:

```bash
# Apply existing migrations
docker-compose exec backend uv run alembic upgrade head
```

If you modify models in `app/models/` and need to generate a new migration script:

```bash
docker-compose exec backend uv run alembic revision --autogenerate -m "description_of_changes"
docker-compose exec backend uv run alembic upgrade head
```

## Testing

Tests are written using `pytest` and configured for async execution with `pytest-asyncio`.

To run the test suite:

```bash
uv run pytest
```

Configuration details for `pytest` can be found in `pytest.ini`. 

## Code Quality

This project uses [Ruff](https://docs.astral.sh/ruff/) for both code linting and formatting. The configurations are specified in `pyproject.toml`.

To check formatting and lint files:
```bash
uv run ruff check .
```

To automatically format the code and fix auto-fixable lint issues:
```bash
uv run ruff format .
uv run ruff check --fix .
```
