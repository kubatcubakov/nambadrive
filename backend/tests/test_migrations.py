import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]


def test_migration_upgrade_downgrade_and_seed(tmp_path):
    database = tmp_path / "migration.db"
    env = {**os.environ, "NAMBADRIVE_DATABASE_URL": "sqlite+aiosqlite:///" + str(database)}

    def migrate(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "head")
    migrate("check")
    engine = create_engine("sqlite:///" + str(database))
    assert "resources" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM roles")) == 10
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM role_permissions rp "
                    "JOIN roles r ON r.id=rp.role_id WHERE r.name IN "
                    "('SYSTEM_ADMIN','STORAGE_ADMIN','GUEST')"
                )
            )
            == 0
        )
    migrate("downgrade", "0002_identity_sessions")
    assert "resources" not in inspect(engine).get_table_names()
    migrate("upgrade", "head")
    migrate("check")
    engine.dispose()
