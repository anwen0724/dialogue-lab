"""场景表单的边界校验。"""

from pydantic import BaseModel, ConfigDict, Field


class SceneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=60)
    character_name: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(min_length=1, max_length=32000)


class SceneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    character_name: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=32000)
