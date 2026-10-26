"""从本次选择的文档加载系统指令，不与会话绑定。"""

from pathlib import Path

from dialogue_lab.sessions.types import SessionError


class SystemPrompts:
    def __init__(self, directory: Path, *extra_directories: Path):
        self.directory = directory
        self.directories = (directory, *extra_directories)

    def load(self, name: str) -> str:
        """名称只能来自目录中的预设，不接收客户端文件路径。"""
        documents = {
            path.stem: path
            for directory in self.directories
            for path in directory.glob("*.md")
            if path.is_file()
        }
        if name not in documents:
            raise SessionError("PRESET_NOT_FOUND", "系统指令不存在。", 404)
        content = documents[name].read_text(encoding="utf-8").strip()
        if not content:
            raise SessionError("PRESET_EMPTY", "系统指令文档为空。")
        return content

    def list(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob("*.md") if path.is_file())
