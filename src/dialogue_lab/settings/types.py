"""设置文件与 HTTP 共用的公开结构，不包含凭据。"""

from pydantic import BaseModel, ConfigDict, Field


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class DialogueSelection(ModelSelection):
    reasoning: str | None = None


class ApplicationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dialogue: DialogueSelection
    stt: ModelSelection
    tts: ModelSelection
