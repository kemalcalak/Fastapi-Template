# ⚡ FastAPI Layered Architecture Template

A modern, production-ready FastAPI template utilizing a clean, layered (hexagonal-style) architecture. This template is designed for building robust and scalable backend services with clear separation of concerns, easy testing, and high maintainability.

## 💡 Why This Template?

While FastAPI is incredibly fast and flexible, it doesn't enforce a specific project structure. As projects grow, they often turn into a tangled mess of tightly coupled route handlers, business logic, and database calls. This template provides **Enterprise-Grade Readiness** from minute zero.

- **Pre-Configured Tooling:** `uv`, `pytest`, `ruff`, and `alembic` are pre-integrated. No wrestling with environment setups.
- **Scalable Architecture:** Extends beyond simple MVC. It isolates API routing, business logic (Services), and database interactions (Repositories) making the app highly testable and maintainable.
- **Production-Ready Security:** JWT authentication, HttpOnly cookies for refresh tokens, token blacklisting, password hashing, and rate limiting are baked in.
- **Docker First:** A `docker-compose.yaml` is ready to spin up your backend and PostgreSQL database instantly.

---

## 🔗 Frontend Compatibility

This backend template is designed to seamlessly integrate with the companion **React + TypeScript + Vite Enterprise Template**.
You can find the frontend template here: [kemalcalak/React-Template](https://github.com/kemalcalak/React-Template).

---

## 🚀 Features & Tech Stack

This template integrates the best-in-class Python ecosystem tools to provide a seamless developer experience:

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) for building APIs with Python 3.12+ based on standard Python type hints.
- **Architecture:** Strict Layered Architecture separating routers, services, repositories, and models, fully utilizing FastAPI's dependency injection.
- **Database & ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) with `asyncpg` for non-blocking operations, and [Alembic](https://alembic.sqlalchemy.org/) for schema migrations.
- **Caching:** [Redis](https://redis.io/) integration using `redis.asyncio` for robust, high-performance distributed caching (e.g. for disposable email validation).
- **Validation & Config:** [Pydantic v2](https://docs.pydantic.dev/latest/) and `pydantic-settings` for robust data validation and environment management.
- **Security & Auth:** Built-in JWT validation, `bcrypt` password hashing, and [Slowapi](https://slowapi.readthedocs.io/en/latest/) for rate limiting.
- **Tooling:** [uv](https://docs.astral.sh/uv/) for blazing-fast package management, and [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.
- **Testing:** Comprehensive async testing setup with `pytest` and `pytest-asyncio`.

---

## ✅ CI/CD Ready

The repository structure supports standard Continuous Integration pipelines out-of-the-box. Ensure you configure your CI (GitHub Actions, GitLab CI, etc.) to run:

1.  **Dependency Install:** `uv sync`
2.  **Linting:** `uv run ruff check .`
3.  **Formatting Check:** `uv run ruff format --check .`
4.  **Unit & Integration Tests:** `uv run pytest`

---

## 📦 Setup & Local Development

### Prerequisites

- Python >= 3.12
- Docker & Docker Compose (for local database and Redis)
- [`uv`](https://docs.astral.sh/uv/) package manager (recommended)

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

Your `.env` file should look like this, filled with your actual configuration:

```env
# Application Settings
PROJECT_NAME="FastAPI Template"
SECRET_KEY="changethis"
ENVIRONMENT="local"
FIRST_SUPERUSER="admin@example.com"
FIRST_SUPERUSER_PASSWORD="changethis"
FRONTEND_HOST="http://localhost:5173"

# Database Settings
POSTGRES_SERVER="localhost"
POSTGRES_PORT=5432
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="changethis"
POSTGRES_DB="app"

# Redis Cache Settings
REDIS_URL="redis://localhost:6379/0"

# Email / SMTP Settings (Optional)
SMTP_HOST="smtp.example.com"
SMTP_PORT=587
SMTP_USE_STARTTLS=True
SMTP_USE_SSL=False
SMTP_USER="smtp_username"
SMTP_PASSWORD="smtp_password"
EMAILS_FROM_EMAIL="noreply@example.com"
```

### 3. Start the Application via Docker

This project provides a `docker-compose.yaml` to spin up the entire stack, including the backend service, a local PostgreSQL instance, and a Redis container:

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

---

## 🛠️ Testing & Code Quality

### Testing

Tests are written using `pytest` and configured for async execution with `pytest-asyncio`. Configuration details can be found in `pytest.ini`.

To run the test suite locally:

```bash
uv run pytest
```

### Code Quality

This project uses [Ruff](https://docs.astral.sh/ruff/) for both code linting and formatting. The configurations are specified in `pyproject.toml`.

- **Check for issues:** `uv run ruff check .`
- **Format code:** `uv run ruff format .`
- **Auto-fix lint issues:** `uv run ruff check --fix .`

---

## 📂 Project Structure

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

---

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

> This project follows [Conventional Commits](https://www.conventionalcommits.org/).

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'feat: Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the MIT License. See the `LICENSE` file at the root of the workspace for more information.
