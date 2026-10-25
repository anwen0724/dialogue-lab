"""集中读取后端配置，环境变量优先于 backend/.env。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """定义应用启动时读取的配置项。"""

    model_config = SettingsConfigDict(
        env_prefix="DIALOGUE_LAB_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "Dialogue Lab"
