from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NAMBADRIVE_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "NambaDrive"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    public_url: str = "http://localhost:8080"

    database_url: str = Field(
        default="postgresql+asyncpg://nambadrive:nambadrive@postgres:5432/nambadrive"
    )
    redis_url: str = "redis://redis:6379/0"

    oidc_issuer: str = ""
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_allowed_algorithms: list[str] = ["RS256"]
    oidc_transaction_ttl_seconds: int = 600
    oidc_clock_skew_seconds: int = 60

    session_cookie_name: str = "nambadrive_session"
    oidc_state_cookie_name: str = "nambadrive_oidc_state"
    session_ttl_seconds: int = 8 * 60 * 60
    cookie_secure: bool = False

    s3_endpoint: str = "http://seaweed:8333"
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

    audit_log_path: str = "/var/log/nambadrive/audit.json"
    csrf_secret: str = "dev-only-change-me"

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
    return Settings()
