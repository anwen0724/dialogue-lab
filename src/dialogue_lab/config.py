"""集中读取应用配置，环境变量优先于项目根目录的 .env。"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """定义应用启动时读取的配置项。"""

    model_config = SettingsConfigDict(
        env_prefix="DIALOGUE_LAB_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        # 同一 .env 可包含 AI 层凭据；本配置只读取自己声明的字段。
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "Dialogue Lab"
    stt_api_key: SecretStr = SecretStr("")
    stt_model: str = "qwen-audio-3.1-asr-flash-streaming"
