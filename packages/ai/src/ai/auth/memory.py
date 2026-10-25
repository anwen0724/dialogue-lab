"""宿主可替换的内存凭据 Store。"""

import asyncio
from copy import deepcopy

from ai.auth.contracts import ModelAuth


class MemoryCredentialStore:
    """串行读改写，返回副本以防绕过 modify 修改存储。"""

    def __init__(self):
        self._values = {}
        self._lock = asyncio.Lock()

    async def read(self, provider_id: str) -> ModelAuth | None:
        return deepcopy(self._values.get(provider_id))

    async def list(self) -> tuple[str, ...]:
        return tuple(self._values)

    async def modify(self, provider_id, update):
        async with self._lock:
            current = deepcopy(self._values.get(provider_id))
            self._values[provider_id] = deepcopy(update(current))

    async def delete(self, provider_id):
        async with self._lock:
            self._values.pop(provider_id, None)
