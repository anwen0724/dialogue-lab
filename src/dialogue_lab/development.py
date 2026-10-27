"""组合数据库启动、版本检查和现有前后端开发服务。"""

import asyncio
import shutil
import socket
import subprocess
from pathlib import Path

import uvicorn
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from dialogue_lab.config import Settings
from dialogue_lab.storage.database import Database


class StartupError(Exception):
    """可直接显示给开发者的启动失败原因。"""


def run_development(root: Path) -> None:
    """前端继承当前终端，后端使用 Uvicorn 原有的热更新和 Ctrl+C 处理。"""
    if not (root / "compose.yaml").is_file() or not (root / "pyproject.toml").is_file():
        raise StartupError("请在 dialogue-lab 项目根目录执行 uv run dialogue-lab dev。")
    frontend = root / "frontend"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.is_file():
        raise StartupError("前端依赖未安装，请进入 frontend 目录执行 npm ci。")
    node = shutil.which("node")
    if node is None:
        raise StartupError("找不到 Node.js，请安装 README 中要求的 Node.js 版本。")
    settings = Settings()
    for port in (settings.backend_port, settings.frontend_port):
        check_port_available(port)

    print("[dev] 启动数据库…", flush=True)
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--wait", "postgres"], cwd=root, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        raise StartupError(
            "数据库启动失败，请确认 Docker Desktop 已启动，并检查上方日志。"
        ) from None
    print("[dev] 检查数据库版本（只读，不执行迁移）…", flush=True)
    asyncio.run(check_database_version(root, settings.database_url.get_secret_value()))

    # 不创建新终端或独立进程组，前后端都直接接收当前终端的 Ctrl+C。
    with subprocess.Popen([node, str(vite), "--clearScreen", "false"], cwd=frontend) as process:
        try:
            uvicorn.run(
                "dialogue_lab.main:app", host="127.0.0.1", port=settings.backend_port, reload=True
            )
        finally:
            # 正常 Ctrl+C 已通知 Vite；后端单独失败时也结束本次前端进程。
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()


def check_port_available(port: int) -> None:
    """只检查绑定权限和占用状态，不终止已有监听进程。"""
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise StartupError(f"端口 {port} 被占用或系统禁止绑定，请处理后重试。") from None


async def check_database_version(root: Path, database_url: str) -> None:
    """只读比较数据库版本和仓库版本，不调用 Alembic 的升级操作。"""
    expected = set(ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads())
    database = Database(database_url)
    try:
        async with asyncio.timeout(10):
            async with database.engine.connect() as connection:
                current = set(
                    await connection.run_sync(
                        lambda sync: MigrationContext.configure(sync).get_current_heads()
                    )
                )
    except Exception:
        raise StartupError("无法读取数据库版本，请检查数据库连接配置和服务状态。") from None
    finally:
        await database.close()
    if current != expected:
        raise StartupError(
            f"数据库版本为 {', '.join(sorted(current)) or '未初始化'}，"
            f"代码需要 {', '.join(sorted(expected))}。"
            "请手动执行 uv run alembic upgrade head，再启动开发环境。"
        )
