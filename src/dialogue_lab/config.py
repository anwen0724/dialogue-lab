"""集中读取应用配置，环境变量优先于项目根目录的 .env。"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://dialogue:dialogue@127.0.0.1:5432/dialogue_lab"
    )
    stt_api_key: SecretStr = SecretStr("")
    stt_model: str = "qwen-audio-3.1-asr-flash-streaming"
    ai_provider: Literal["deepseek", "openai", "anthropic"] = "deepseek"
    ai_model: str = "deepseek-flash"
    ai_api_key: SecretStr = SecretStr("")
    ai_reasoning: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    ai_max_output_tokens: int = Field(default=4096, gt=0)
    tts_api_key: SecretStr = SecretStr("")
    tts_model: str = "qwen-audio-3.1-tts-flash"
    tts_voice: str = "longanhuan_v3.1"
    prompts_directory: Path = Path(__file__).resolve().parents[2] / "prompts"

    data_directory: Path = Path(__file__).resolve().parents[2] / "data"
