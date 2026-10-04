from app.core.config import Settings


def test_redirect_uri_is_derived_from_public_url() -> None:
    settings = Settings(
        public_url="https://drive.example.test/",
        oidc_issuer="https://auth.example.test/application/o/nambadrive/",
        oidc_discovery_url=(
            "https://auth.example.test/application/o/nambadrive/.well-known/openid-configuration"
        ),
        oidc_client_id="nambadrive",
        oidc_client_secret="secret",
    )
    assert settings.oidc_redirect_uri == "https://drive.example.test/api/v1/auth/callback"
    assert settings.oidc_configured is True
