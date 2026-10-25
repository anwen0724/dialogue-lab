"""组合供应商身份、认证、静态目录与协议适配器。"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from ai._internal.resources import close_all
from ai.api.base import ApiAdapter
from ai.auth.contracts import AuthResolver
from ai.types.model import Model


class Provider(Protocol):
    id: str
    auth: AuthResolver

    def get_models(self) -> tuple[Model, ...]: ...
    def stream(self, model, context, auth, options): ...
    def stream_simple(self, model, context, auth, options): ...
    async def aclose(self) -> None: ...


class _ComposedProvider:
    """通用供应商只选择协议，不解释供应商响应。"""

    def __init__(self, id, models, auth, adapters):
        self.id = id
        self.auth = auth
        self._models = tuple(models)
        self._adapters = dict(adapters)

    def get_models(self):
        return self._models

    def stream(self, model, context, auth, options):
        return self._adapters[model.api].stream(model, context, auth, options)

    def stream_simple(self, model, context, auth, options):
        return self._adapters[model.api].stream_simple(model, context, auth, options)

    async def aclose(self):
        await close_all({id(a): a for a in self._adapters.values()}.values())


def create_provider(
    id: str,
    *,
    models: Sequence[Model] = (),
    auth: AuthResolver,
    adapters: Mapping[str, ApiAdapter],
) -> Provider:
    """组合现有协议；静态目录仅用于发现，调用不受目录白名单限制。"""
    if len({m.id for m in models}) != len(models):
        raise ValueError("Duplicate model id in provider catalog")
    if any(m.provider != id for m in models):
        raise ValueError("Catalog model provider does not match provider id")
    return _ComposedProvider(id, models, auth, adapters)
