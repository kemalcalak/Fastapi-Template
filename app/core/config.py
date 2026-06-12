import os
import secrets
import warnings
from typing import Annotated, Literal, Self

from pydantic import (
    AnyUrl,
    BeforeValidator,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: object) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes — short-lived access token limits the blast radius of a
    # stolen token. Clients transparently renew via the refresh-token flow.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    # Account lockout: after MAX failed logins within the WINDOW, the account is
    # locked for LOCKOUT seconds. Closes distributed brute-force that the
    # per-IP rate limit cannot (attempts keyed by email, not source IP).
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_FAILED_ATTEMPT_WINDOW_SECONDS: int = 15 * 60
    LOGIN_LOCKOUT_SECONDS: int = 15 * 60
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEFAULT_LANGUAGE: Literal["en", "tr"] = "en"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        origins = [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS]
        if self.FRONTEND_HOST:
            origins.append(str(self.FRONTEND_HOST).rstrip("/"))
        return origins

    # Host header allowlist enforced by TrustedHostMiddleware. Comma-separated
    # in the environment (e.g. ``api.example.com,example.com``).
    ALLOWED_HOSTS: Annotated[list[str] | str, BeforeValidator(parse_cors)] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted_hosts(self) -> list[str]:
        """Hosts accepted by ``TrustedHostMiddleware``.

        Outside production we return ``["*"]`` so local dev and the test client
        (which sends ``Host: testserver``) are never blocked. Production
        enforces the explicit ``ALLOWED_HOSTS`` list plus the frontend host,
        falling back to ``["*"]`` only if nothing was configured so a missing
        value can never brick the deployment.
        """
        if self.ENVIRONMENT != "production":
            return ["*"]

        from urllib.parse import urlparse

        hosts = [h.strip() for h in self.ALLOWED_HOSTS if h.strip()]
        if self.FRONTEND_HOST:
            hostname = urlparse(str(self.FRONTEND_HOST)).hostname
            if hostname:
                hosts.append(hostname)
        return hosts or ["*"]

    PROJECT_NAME: str
    SENTRY_DSN: str | None = None

    # Bearer token required to scrape /metrics outside ENVIRONMENT="local".
    # When unset (or wrong), /metrics returns 404 to mirror origin_check_middleware
    # and avoid disclosing endpoint existence. Local dev keeps /metrics open.
    METRICS_TOKEN: str | None = None

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USE_STARTTLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: str = "noreply@example.com"

    # Cloudinary (file/avatar storage). Optional at boot; uploads fail
    # clearly at request time when these are unset.
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    CLOUDINARY_UPLOAD_FOLDER: str = "uploads"

    # Reject uploads larger than this (bytes). Enforced in the upload service.
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB

    REDIS_URL: str = "redis://localhost:6379/0"

    # Disposable-email blocklist source. Points to the community-maintained
    # ``disposable-email-domains`` repo; override for air-gapped deployments.
    DISPOSABLE_EMAIL_LIST_URL: str = (
        "https://raw.githubusercontent.com/disposable-email-domains/"
        "disposable-email-domains/master/disposable_email_blocklist.conf"
    )
    DISPOSABLE_EMAIL_CACHE_TTL_SECONDS: int = 60 * 60 * 24

    # Account deactivation + grace-period deletion
    ACCOUNT_DELETION_GRACE_DAYS: int = 30
    DELETION_JOB_BATCH_SIZE: int = 100
    DELETION_JOB_CRON_HOUR: int = 3
    DELETION_JOB_CRON_MINUTE: int = 0

    # Session housekeeping: revoked rows are kept this long for audit trails,
    # then swept (expired rows go immediately) by the nightly purge job.
    SESSION_REVOKED_RETENTION_DAYS: int = 30
    SESSION_PURGE_CRON_HOUR: int = 4
    SESSION_PURGE_CRON_MINUTE: int = 0

    # Database connection pool (tuned per API worker)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        from urllib.parse import quote_plus

        password = quote_plus(self.POSTGRES_PASSWORD) if self.POSTGRES_PASSWORD else ""
        url_str = (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
        return PostgresDsn(url_str)

    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        is_blank = not (value or "").strip()
        if value == "changethis" or is_blank:
            reason = "empty" if is_blank else 'the insecure default "changethis"'
            message = (
                f"The value of {var_name} is {reason}; "
                "for security, please set it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        # SECRET_KEY defaults to a random value at import time. That is fine
        # for local dev but catastrophic in staging/prod because every restart
        # invalidates all issued tokens. Require an explicit env value outside
        # local.
        if self.ENVIRONMENT != "local" and not os.getenv("SECRET_KEY"):
            raise ValueError(
                "SECRET_KEY must be set explicitly via environment for "
                f"ENVIRONMENT={self.ENVIRONMENT!r}."
            )
        return self


settings = Settings()  # type: ignore
