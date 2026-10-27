"""保护启动前检查；前后端启动和 Ctrl+C 使用真实命令验收。"""

import socket
import subprocess
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import TEST_DATABASE_URL
from sqlalchemy import text

from dialogue_lab.development import (
    StartupError,
    check_database_version,
    check_port_available,
    run_development,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("setting", ["DIALOGUE_LAB_BACKEND_PORT", "DIALOGUE_LAB_FRONTEND_PORT"])
def test_configured_port_is_checked_before_starting_services(monkeypatch, setting):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setenv(setting, str(port))

        def unexpected_start(*args, **kwargs):
            raise AssertionError("占用的配置端口应在启动任何服务前被拒绝")

        monkeypatch.setattr(subprocess, "run", unexpected_start)
        with pytest.raises(StartupError, match=str(port)):
            run_development(ROOT)


def test_unavailable_docker_stops_startup_with_actionable_message(monkeypatch):
    def unavailable(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(StartupError, match="Docker"):
        run_development(ROOT)


def test_missing_frontend_dependencies_explains_install_command(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "compose.yaml").touch()
    (tmp_path / "frontend").mkdir()
    with pytest.raises(StartupError, match="npm ci"):
        run_development(tmp_path)


def test_occupied_port_is_rejected_without_closing_the_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(StartupError, match=str(port)):
            check_port_available(port)
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass


@pytest.mark.asyncio
async def test_current_database_is_accepted_without_changing_version(database):
    async with database.engine.connect() as connection:
        before = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    await check_database_version(ROOT, TEST_DATABASE_URL)
    async with database.engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["0002", None], ids=["outdated", "uninitialized"])
async def test_outdated_database_is_rejected_without_applying_migrations(database, version):
    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    assert len(heads) == 1
    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM alembic_version"))
        if version is not None:
            await connection.execute(
                text("INSERT INTO alembic_version VALUES (:version)"), {"version": version}
            )
    try:
        with pytest.raises(StartupError, match="uv run alembic upgrade head"):
            await check_database_version(ROOT, TEST_DATABASE_URL)
        async with database.engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == version
            )
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(text("DELETE FROM alembic_version"))
            await connection.execute(
                text("INSERT INTO alembic_version VALUES (:version)"), {"version": heads[0]}
            )
