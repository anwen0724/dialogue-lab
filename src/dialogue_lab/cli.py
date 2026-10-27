"""项目开发命令入口。"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from dialogue_lab.development import StartupError, run_development


def main(argv: list[str] | None = None) -> int:
    """选择开发命令，启动与退出沿用现有服务的行为。"""
    parser = argparse.ArgumentParser(prog="dialogue-lab", description="Dialogue Lab 项目命令")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("dev", help="启动开发环境；数据库迁移需要手动执行")
    parser.parse_args(argv)
    try:
        run_development(Path.cwd())
    except KeyboardInterrupt:
        pass
    except (StartupError, OSError) as error:
        print(f"[dev] {error}", file=sys.stderr)
        return 1
    except ValidationError:
        print("[dev] 配置格式无效，请检查 .env 的配置项。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
