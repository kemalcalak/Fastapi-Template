"""Locust load-test scenarios for the FastAPI template.

Run the API with ENVIRONMENT=local so slowapi rate limiting is disabled,
otherwise the test measures the rate limiter instead of real capacity.

Pick a scenario by its class name, e.g.:

    uv run locust -f loadtest/locustfile.py ActiveUser --host http://localhost:8000

Scenarios:
    ActiveUser       Realistic "concurrent active user": login once, then poll
                     GET /users/me with think time. Use this to find how many
                     simultaneous users the system serves.
    HealthCeilingUser Raw throughput ceiling: GET /health/live, no DB, no wait.
    LoginStormUser   bcrypt bottleneck: repeated POST /auth/login.

Seed login accounts first with loadtest/seed_users.py.
"""

import os
import random

from locust import HttpUser, between, constant, task

# --- Configuration via environment variables -------------------------------

API_PREFIX = os.getenv("LT_API_PREFIX", "/api/v1")
EMAIL_PREFIX = os.getenv("LT_EMAIL_PREFIX", "loadtest+")
EMAIL_DOMAIN = os.getenv("LT_EMAIL_DOMAIN", "example.com")
PASSWORD = os.getenv("LT_PASSWORD", "LoadTest123!")
USER_COUNT = int(os.getenv("LT_USER_COUNT", "50"))
WAIT_MIN = float(os.getenv("LT_WAIT_MIN", "2"))
WAIT_MAX = float(os.getenv("LT_WAIT_MAX", "10"))


def _credentials() -> tuple[str, str]:
    """Return a (email, password) pair for a random seeded account."""
    index = random.randint(0, USER_COUNT - 1)
    return f"{EMAIL_PREFIX}{index}@{EMAIL_DOMAIN}", PASSWORD


def _login(client) -> bool:
    """Log in via the OAuth2 form endpoint; cookies are stored on the session.

    Returns True on success so callers can mark the request outcome.
    """
    email, password = _credentials()
    with client.post(
        f"{API_PREFIX}/auth/login",
        data={"username": email, "password": password},
        name="POST /auth/login",
        catch_response=True,
    ) as response:
        if response.status_code == 200:
            response.success()
            return True
        response.failure(f"login failed: {response.status_code} {response.text[:200]}")
        return False


class ActiveUser(HttpUser):
    """Realistic active user: authenticate once, then browse with think time."""

    wait_time = between(WAIT_MIN, WAIT_MAX)

    def on_start(self) -> None:
        """Authenticate before issuing browsing requests."""
        self._authenticated = _login(self.client)

    @task
    def read_me(self) -> None:
        """Fetch the current user's profile — a typical authenticated read."""
        if not self._authenticated:
            self._authenticated = _login(self.client)
            return
        self.client.get(f"{API_PREFIX}/users/me", name="GET /users/me")


class HealthCeilingUser(HttpUser):
    """Raw throughput ceiling: hammer the dependency-free liveness probe."""

    wait_time = constant(0)

    @task
    def liveness(self) -> None:
        """Hit the liveness endpoint with no think time."""
        self.client.get(f"{API_PREFIX}/health/live", name="GET /health/live")


class LoginStormUser(HttpUser):
    """bcrypt bottleneck: every request triggers a password hash verification."""

    wait_time = constant(0)

    @task
    def login(self) -> None:
        """Perform a fresh login each iteration to stress bcrypt."""
        _login(self.client)
