import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.auth.oidc import OIDCClient, safe_next_url
from app.core.config import Settings, get_settings
from app.main import app
from app.models.acl import ACLEntry, RoleBinding
from app.models.organization import Department, DepartmentManager
from app.models.resource import Resource
from app.security.logging import configure_transport_logging
from tests.test_authorization import NOW, acl, authorize, binding, scene  # noqa: F401, F811


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.invalid",
        "//evil.invalid",
        "/\\evil.invalid",
        "/%5cevil.invalid",
        "/%2f%2fevil.invalid",
        "/%0d%0aLocation:evil",
        "/\x00evil",
    ],
)
def test_oidc_redirect_rejects_external_encoded_and_control_targets(target):
    assert safe_next_url(target) == "/"


def test_oidc_local_redirect_and_provider_scoped_cache():
    assert safe_next_url("/drive?section=favorites") == "/drive?section=favorites"
    first = OIDCClient(Settings(oidc_issuer="https://a.invalid/", oidc_client_id="a"))
    second = OIDCClient(Settings(oidc_issuer="https://b.invalid/", oidc_client_id="a"))
    assert first.cache_scope != second.cache_scope


def test_production_rejects_development_defaults_without_secret_in_error():
    with pytest.raises(ValueError) as failure:
        Settings(app_env="production", oidc_client_secret="never-print-this-secret")
    assert "never-print-this-secret" not in str(failure.value)


def test_private_settings_mount_and_symlinks(tmp_path, monkeypatch):
    root = tmp_path / "settings"
    root.mkdir(mode=0o700)
    secret = root / "csrf_secret"
    secret.write_text("private-mounted-value")
    secret.chmod(0o600)
    monkeypatch.setenv("NAMBADRIVE_SECRETS_DIR", str(root))
    get_settings.cache_clear()
    try:
        assert get_settings().csrf_secret == "private-mounted-value"
        secret.chmod(0o644)
        get_settings.cache_clear()
        with pytest.raises(ValueError):
            get_settings()
        secret.unlink()
        secret.symlink_to(tmp_path / "outside")
        get_settings.cache_clear()
        with pytest.raises(OSError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_http_transport_logs_do_not_export_url_secrets(caplog):
    configure_transport_logging()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").info(
            "https://api.telegram.org/botprivate-capability/sendMessage"
        )
        logging.getLogger("httpcore.http11").debug("private SDK request payload")
    assert "private-capability" not in caplog.text
    assert "private SDK" not in caplog.text


def test_api_security_headers_and_private_edge_paths():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("change", ["acl", "binding", "manager", "department", "owner", "hold"])
async def test_reauthorization_refreshes_cached_security_rows(db, scene, change):  # noqa: F811
    owner, outsider, space, folder, doc, dept, child = scene
    actor, permission = outsider, "VIEW"
    model, identifier, values = None, None, None
    if change == "acl":
        row = await acl(db, scene)
        model, identifier, values = ACLEntry, ACLEntry.id == row.id, {"effect": "DENY"}
    elif change == "binding":
        row = await binding(db, outsider, "READER", space)
        model, identifier, values = RoleBinding, RoleBinding.id == row.id, {"revoked_at": NOW}
    elif change == "manager":
        row = DepartmentManager(
            user_id=outsider.id, department_id=dept.id, valid_from=NOW - timedelta(days=1)
        )
        db.add(row)
        await db.commit()
        model, identifier, values = (
            DepartmentManager,
            DepartmentManager.user_id == outsider.id,
            {"revoked_at": NOW},
        )
    elif change == "department":
        actor = owner
        model, identifier, values = Department, Department.id == child.id, {"enabled": False}
    elif change == "owner":
        actor = owner
        model, identifier, values = (
            Resource,
            Resource.id.in_([space.id, folder.id, doc.id]),
            {"owner_user_id": outsider.id},
        )
    else:
        actor, permission = owner, "PURGE"
        doc.state, doc.deleted_at = "TRASH", NOW - timedelta(days=31)
        await db.commit()
        model, identifier, values = Resource, Resource.id == doc.id, {"legal_hold": True}
    assert (await authorize(db, actor, doc, permission)).allowed
    # Simulate a concurrent writer without synchronizing the already loaded identity map.
    await db.execute(
        update(model)
        .where(identifier)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    assert not (await authorize(db, actor, doc, permission)).allowed


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.invalid/token",
        "http://auth.invalid/token",
        "https://user:secret@auth.invalid/token",
    ],
)
def test_oidc_discovery_cannot_redirect_credentials_to_another_origin(endpoint):
    from app.auth.oidc import OIDCError

    client = OIDCClient(Settings(oidc_issuer="https://auth.invalid/provider/"))
    metadata = {
        "issuer": "https://auth.invalid/provider/",
        "authorization_endpoint": "https://auth.invalid/authorize",
        "token_endpoint": endpoint,
        "jwks_uri": "https://auth.invalid/jwks",
    }
    with pytest.raises(OIDCError):
        client.validated_metadata(metadata)


def test_valid_production_settings_preserve_strong_controls():
    settings = Settings(
        app_env="production",
        cookie_secure=True,
        public_url="https://drive.invalid",
        oidc_issuer="https://auth.invalid/provider/",
        oidc_discovery_url="https://auth.invalid/discovery",
        oidc_client_id="drive",
        oidc_client_secret="provider-issued-private-secret",
        database_url="postgresql+asyncpg://drive:strong-private-database-password@db.invalid/drive?ssl=verify-full",
        csrf_secret="c" * 43,
        s3_endpoint="https://s3.invalid",
        s3_access_key="private-access-key",
        s3_secret_key="s" * 43,
        office_public_url="https://office.invalid",
        office_browser_secret="b" * 43,
        office_outbox_secret="o" * 43,
        scim_token="i" * 43,
        opensearch_url="https://search.invalid",
        opensearch_username="indexer",
        opensearch_password="p" * 43,
        opensearch_ca_file="/tls/ca.crt",
    )
    assert settings.cookie_secure
