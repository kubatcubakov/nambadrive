from functools import lru_cache

from pydantic import Field, computed_field
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
