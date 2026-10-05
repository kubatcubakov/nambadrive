"""Read-only deployment contract gate. Does not start containers or inspect secrets."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKERS = {
    "scan-worker",
    "search-worker",
    "cleanup-worker",
    "notifications-worker",
    "reviews-worker",
    "lifecycle-worker",
}


def check():
    images = json.loads((ROOT / "deploy/common/images.lock.json").read_text())
    assert all(
        re.fullmatch(r".+:.*@sha256:[a-f0-9]{64}", value) for value in images.values()
    )
    for profile in ("aio", "prod-compact", "prod-distributed"):
        paths = list((ROOT / "deploy" / profile).glob("*compose.yml"))
        assert paths
        all_services = {}
        for path in paths:
            config = yaml.safe_load(path.read_text())
            for name, service in config["services"].items():
                all_services[name] = service
                assert "no-new-privileges:true" in service["security_opt"], (path, name)
                assert service["cap_drop"] == ["ALL"], (path, name)
                assert service["mem_limit"] and service["pids_limit"], (path, name)
                assert (
                    not service.get("privileged")
                    and service.get("network_mode") != "host"
                )
                assert not any("docker.sock" in v for v in service.get("volumes", []))
                if "image" in service:
                    assert "@sha256:" in service["image"], (path, name)
                for port in service.get("ports", []):
                    host, published, target = port.rsplit(":", 2)
                    if name in ("nginx", "office-gateway"):
                        assert host == "${PUBLIC_IP:?}" and published in {"80", "443"}
                    else:
                        assert host == "${PRIVATE_IP:?}", (path, name, port)
                if name in {"backend", "frontend", "tika"} | WORKERS:
                    assert service["read_only"] and service["user"] != "0"
            assert all(
                config["networks"][n]["internal"]
                for n in ("app", "services", "cache", "av", "parser")
            )
        assert WORKERS <= all_services.keys()
        assert {
            "backend",
            "frontend",
            "nginx",
            "scim-gateway",
            "office-backchannel",
            "postgres",
            "opensearch",
            "redis",
            "tika",
            "clamav",
            "onlyoffice",
            "filer",
            "s3",
            "s3-gateway",
        } <= all_services.keys()
        assert not all_services["redis"].get("ports")
        assert all_services["redis"]["networks"] == ["cache"]
        assert all_services["tika"]["networks"] == ["parser"]
        assert all_services["clamav"]["networks"] == ["av", "egress"]
        assert not all_services["backend"].get("ports")
        assert (
            all_services["backend"]["environment"]["NAMBADRIVE_APP_ENV"] == "production"
        )
        assert (
            all_services["backend"]["environment"]["NAMBADRIVE_COOKIE_SECURE"] == "true"
        )
        assert all_services["onlyoffice"]["environment"]["JWT_ENABLED"] == "true"
        assert "egress" not in all_services["onlyoffice"]["networks"]
        if profile != "aio":
            assert {
                "master01",
                "master02",
                "master03",
                "volume01",
                "volume02",
            } <= all_services.keys()
            for i in (1, 2, 3):
                assert (
                    "-defaultReplication=001"
                    in all_services[f"master{i:02}"]["command"]
                )
                assert (
                    "-peers=${MASTER_PEERS:?}"
                    in all_services[f"master{i:02}"]["command"]
                )
        else:
            assert not all_services["s3-gateway"].get("ports")
    assert (ROOT / "deploy/common/postgres/wal.py").read_bytes() == (
        ROOT / "backend/app/backup/wal.py"
    ).read_bytes()
    nginx = (ROOT / "deploy/common/nginx/proxy-private.conf").read_text()
    assert (
        "$proxy_add_x_forwarded_for" not in nginx
        and "X-Forwarded-For $remote_addr" in nginx
    )
    assert (
        "ssl_verify_client on"
        in (ROOT / "deploy/common/nginx/scim.conf.template").read_text()
    )
    assert (
        "location ^~ /scim/ { return 404; }"
        in (ROOT / "deploy/common/nginx/app.conf.template").read_text()
    )
    print("Three deployment profiles: security/topology contract passed")


if __name__ == "__main__":
    check()
