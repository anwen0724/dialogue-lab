"""认证扩展接口；凭据按 Provider 保存，不携带业务会话。"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from ai.types.model import Model


@dataclass
class ModelAuth:
    """api_key 为 None 且对象存在，表示明确的免密认证。"""

    api_key: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    base_url: str | None = None


class CredentialStore(Protocol):
    async def read(self, provider_id: str) -> ModelAuth | None: ...
    async def list(self) -> tuple[str, ...]: ...
    async def modify(
        self, provider_id: str, update: Callable[[ModelAuth | None], ModelAuth]
    ) -> None: ...
    async def delete(self, provider_id: str) -> None: ...


class AuthContext:
    """默认读取进程环境；传入映射时只读取该映射。"""

    def __init__(self, environment: Mapping[str, str] | None = None):
        self._environment = os.environ if environment is None else environment

    def get_env(self, name: str) -> str | None:
        return self._environment.get(name)


class AuthResolver(Protocol):
    async def resolve(
        self,
        model: Model,
        store: CredentialStore,
        context: AuthContext,
        override: ModelAuth | None = None,
    ) -> ModelAuth | None: ...
