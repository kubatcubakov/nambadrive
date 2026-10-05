import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NAMBADRIVE_",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "NambaDrive"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    public_url: str = "http://localhost:8080"

    database_url: str = Field(
        default="postgresql+asyncpg://nambadrive:nambadrive@postgres:5432/nambadrive", repr=False
    )
    redis_url: str = Field(default="redis://redis:6379/0", repr=False)

    scim_token: SecretStr = SecretStr("")

    oidc_issuer: str = ""
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = Field(default="", repr=False)
    oidc_jit_provisioning: bool = False
    oidc_allowed_algorithms: list[str] = ["RS256"]
    oidc_transaction_ttl_seconds: int = 600
    oidc_clock_skew_seconds: int = 60

    session_cookie_name: str = "nambadrive_session"
    oidc_state_cookie_name: str = "nambadrive_oidc_state"
    session_ttl_seconds: int = 8 * 60 * 60
    cookie_secure: bool = False

    s3_endpoint: str = "http://seaweed:8333"
    http_ca_file: str | None = None
    office_public_url: str = ""
    office_internal_url: str = "http://onlyoffice"
    office_backend_url: str = "http://backend:8000"
    office_browser_secret: SecretStr = SecretStr("")
    office_outbox_secret: SecretStr = SecretStr("")
    office_session_seconds: int = Field(default=1800, ge=60, le=3600)
    clamav_host: str = "clamav"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    tika_url: str = "http://tika:9998"
    opensearch_url: str = "https://opensearch:9200"
    opensearch_username: str = ""
    opensearch_password: SecretStr = SecretStr("")
    opensearch_ca_file: str | None = None
    search_index: str = "nambadrive-documents-v1"
    search_text_max_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_data_bucket: str = "nambadrive-data"
    s3_quarantine_bucket: str = "nambadrive-quarantine"
    upload_max_bytes: int = Field(default=500 * 1024 * 1024, ge=1)

    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_ca_file: str | None = None
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_admin_chat_id: SecretStr = SecretStr("")

    audit_log_path: str = "/var/log/nambadrive/audit.json"
    csrf_secret: str = Field(default="dev-only-change-me", repr=False)

    @model_validator(mode="after")
    def production_security(self) -> "Settings":
        if self.app_env != "production":
            return self
        urls = (
            self.public_url,
            self.oidc_issuer,
            self.oidc_discovery_url,
            self.s3_endpoint,
            self.opensearch_url,
            self.office_public_url,
        )
        if not self.cookie_secure or not self.oidc_configured:
            raise ValueError("Production requires secure cookies and configured OIDC")
        for value in urls:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Production requires authenticated HTTPS origins")
        database = urlsplit(self.database_url)
        if (
            database.scheme != "postgresql+asyncpg"
            or not database.password
            # Reject the legacy development default; this is not a credential assignment.
            or database.password in {"nambadrive", "postgres", "password"}
            or "CHANGE_ME" in self.database_url
            or parse_qs(database.query).get("ssl") != ["verify-full"]
        ):
            raise ValueError(
                "Production PostgreSQL requires explicit credentials and verify-full TLS"
            )
        required = (
            self.csrf_secret,
            self.oidc_client_secret,
            self.office_browser_secret.get_secret_value(),
            self.office_outbox_secret.get_secret_value(),
            self.scim_token.get_secret_value(),
            self.s3_access_key.get_secret_value(),
            self.s3_secret_key.get_secret_value(),
            self.opensearch_password.get_secret_value(),
        )
        if any(
            not value or "CHANGE_ME" in value or value == "dev-only-change-me" for value in required
        ):
            raise ValueError("Production credentials must be explicitly configured")
        if any(
            len(value) < 32
            for value in (
                self.csrf_secret,
                self.office_browser_secret.get_secret_value(),
                self.office_outbox_secret.get_secret_value(),
            )
        ):
            raise ValueError("Production cryptographic secrets must have at least 32 characters")
        if (
            self.office_browser_secret == self.office_outbox_secret
            or len(self.scim_token.get_secret_value()) < 43
        ):
            raise ValueError("Distinct Office keys and a strong SCIM capability are required")
        if not self.opensearch_username or not self.opensearch_ca_file:
            raise ValueError("Production search requires credentials and a trusted CA")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oidc_redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}{self.api_v1_prefix}/auth/callback"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oidc_configured(self) -> bool:
        return bool(
            self.oidc_issuer
            and self.oidc_discovery_url
            and self.oidc_client_id
            and self.oidc_client_secret
        )


@lru_cache
def get_settings() -> Settings:
    from app.security.logging import configure_transport_logging

    configure_transport_logging()
    directory = os.environ.get("NAMBADRIVE_SECRETS_DIR")
    values: dict[str, Any] = {}
    if directory:
        root = Path(directory)
        info = root.lstat()
        if not root.is_absolute() or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("Private mounted settings directory required")
        for path in root.iterdir():
            if path.name not in Settings.model_fields:
                raise ValueError("Unknown mounted setting")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid not in {0, os.geteuid()}
                    or info.st_mode & 0o077
                    or info.st_nlink != 1
                ):
                    raise ValueError("Private regular mounted setting required")
                raw = source.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Mounted setting exceeds limit")
                values[path.name] = raw.decode().rstrip("\n")
    return Settings(**values)
