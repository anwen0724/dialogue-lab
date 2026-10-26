"""供应商集合与统一调用入口，不承担宿主 runtime 调度。"""

import asyncio
import time
from dataclasses import asdict
from types import MappingProxyType

from ai._internal.resources import cancel_on_signal, close_all, closing_iterator
from ai.auth.contracts import AuthContext, CredentialStore, ModelAuth
from ai.auth.memory import MemoryCredentialStore
from ai.auth.resolve import prepare_auth
from ai.context import normalize_context
from ai.errors import ErrorInfo
from ai.hooks import DiagnosticEvent, observe
from ai.provider import Provider
from ai.stream import AssistantMessageStream
from ai.types.events import AssistantMessageEvent
from ai.types.messages import AssistantMessage, Context
from ai.types.model import Model
from ai.types.options import AbortController, RequestOptions, SimpleOptions


class Models:
    """每个集合独立注册，外部 Provider 默认借用。"""

    def __init__(
        self, credentials: CredentialStore | None = None, auth_context: AuthContext | None = None
    ):
        self.credentials = credentials if credentials is not None else MemoryCredentialStore()
        self.auth_context = auth_context if auth_context is not None else AuthContext()
        self._providers = {}
        self._tasks = set()
        self._controllers = {}
        self._owned = {}
        self._closed = False
        self._active = {}
        self._cleanup = set()
        self._background_errors = []
        self._close_task = None

    def set_provider(self, provider: Provider, *, owns_provider: bool = False) -> None:
        """注册或替换供应商；借用关系不转移关闭责任。"""
        if self._closed:
            raise RuntimeError("Models is closed")
        previous = self._providers.get(provider.id)
        self._providers[provider.id] = provider
        if owns_provider:
            self._owned[id(provider)] = provider
        if previous is not None and previous is not provider:
            self._schedule_retirement(previous)

    def _schedule_retirement(self, provider):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 尚未进入异步运行时的资源由首次运行或 aclose 回收。
            return
        task = loop.create_task(self._retire(provider))
        self._cleanup.add(task)
        task.add_done_callback(self._cleanup_finished)

    def _cleanup_finished(self, task):
        self._cleanup.discard(task)
        self._record_failure(task)

    def _record_failure(self, task):
        if task.cancelled():
            self._background_errors.append(asyncio.CancelledError())
        elif task.exception() is not None:
            self._background_errors.append(task.exception())

    def get_provider(self, provider_id: str) -> Provider | None:
        """按 ID 查询注册对象，不存在时返回 None。"""
        return self._providers.get(provider_id)

    def delete_provider(self, provider_id: str) -> None:
        """只移除后续调用的注册，不删除凭据或中断活动请求。"""
        provider = self._providers.pop(provider_id, None)
        if provider is not None:
            self._schedule_retirement(provider)

    def get_models(self, provider_id: str | None = None) -> tuple[Model, ...]:
        """返回静态目录集合，不访问网络。"""
        providers = (self._providers.get(provider_id),) if provider_id else self._providers.values()
        return tuple(model for p in providers if p is not None for model in p.get_models())

    def get_model(self, provider_id: str, model_id: str) -> Model | None:
        return next((m for m in self.get_models(provider_id) if m.id == model_id), None)

    async def get_auth(self, model: Model, override: ModelAuth | None = None) -> ModelAuth | None:
        """解析认证，不通过生成请求探测密钥；返回值包含敏感数据。"""
        provider = self._providers.get(model.provider)
        if provider is None:
            raise ValueError(f"Provider is not registered: {model.provider}")
        return await provider.auth.resolve(model, self.credentials, self.auth_context, override)

    async def get_available_models(self) -> tuple[Model, ...]:
        """按已配置认证筛选，不宣称凭据已通过真实验证。"""
        available = []
        for model in self.get_models():
            if await self.get_auth(model) is not None:
                available.append(model)
        return tuple(available)

    async def _retire(self, provider):
        if any(p is provider for p in self._providers.values()):
            return
        if any(p is provider for p in self._active.values()):
            return
        owned = self._owned.pop(id(provider), None)
        if owned is not None:
            await owned.aclose()

    def stream_simple(
        self,
        model: Model,
        context: Context,
        options: SimpleOptions | None = None,
    ) -> AssistantMessageStream:
        """使用通用参数立即启动异步生产。"""
        return self._start(model, context, options or SimpleOptions(), simple=True)

    def stream(
        self,
        model: Model,
        context: Context,
        options: RequestOptions | None = None,
    ) -> AssistantMessageStream:
        """使用协议专用参数，返回同一事件与终态契约。"""
        return self._start(model, context, options or RequestOptions(), simple=False)

    def _start(self, model, context, options, *, simple):
        if self._closed:
            raise RuntimeError("Models is closed")
        transcript = normalize_context(context)
        stream = AssistantMessageStream()
        controller = AbortController()
        task = asyncio.create_task(
            self._produce(
                stream,
                model,
                transcript,
                options,
                simple,
                controller.signal,
                time.monotonic(),
            )
        )
        self._tasks.add(task)
        self._controllers[task] = controller
        task.add_done_callback(self._finished)
        return stream

    def _finished(self, task):
        self._tasks.discard(task)
        self._controllers.pop(task, None)
        self._record_failure(task)

    async def _produce(self, stream, model, transcript, options, simple, close_signal, started):
        watchers = []
        provider = None
        first_event = True
        first_text = True

        async def report(kind, data=None):
            await observe(
                options.observer,
                DiagnosticEvent(
                    kind,
                    time.monotonic() - started,
                    model.provider,
                    model.id,
                    MappingProxyType(data or {}),
                ),
            )

        async def publish(event):
            nonlocal first_event, first_text
            if first_event:
                first_event = False
                await report("first_event")
            if first_text and event.type == "text_delta" and event.delta:
                first_text = False
                await report("first_text")
            if event.type in ("done", "error"):
                await report(
                    "end",
                    {
                        "stop_reason": event.partial.stop_reason,
                        "usage": MappingProxyType(asdict(event.partial.usage)),
                        "error_code": event.partial.error.code if event.partial.error else None,
                    },
                )
            stream._push(event)

        try:
            for signal in (close_signal, options.signal):
                if signal is None:
                    continue
                if signal.aborted:
                    raise asyncio.CancelledError
                watchers.append(
                    asyncio.create_task(
                        cancel_on_signal(
                            asyncio.current_task(),
                            signal,
                        )
                    )
                )
            await report("start")
            provider = self._providers[model.provider]
            self._active[asyncio.current_task()] = provider
            auth = await provider.auth.resolve(
                model,
                self.credentials,
                self.auth_context,
                options.auth,
            )
            if auth is None:
                raise ValueError(f"Missing credentials for {model.provider}")
            auth = await prepare_auth(auth, model, options)
            method = provider.stream_simple if simple else provider.stream
            async with closing_iterator(method(model, transcript, auth, options)) as events:
                async for event in events:
                    await publish(event)
        except asyncio.CancelledError:
            message = AssistantMessage(
                model.provider,
                model.id,
                model.api,
                stop_reason="aborted",
                error=ErrorInfo("aborted", "Request aborted"),
            )
            await publish(AssistantMessageEvent("error", message))
        except Exception as exc:
            message = AssistantMessage(
                model.provider,
                model.id,
                model.api,
                stop_reason="error",
                error=ErrorInfo("preparation_error", str(exc)),
            )
            await publish(AssistantMessageEvent("error", message))
        finally:
            for watcher in watchers:
                watcher.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)
            self._active.pop(asyncio.current_task(), None)
            if provider is not None:
                await self._retire(provider)

    async def complete_simple(
        self,
        model: Model,
        context: Context,
        options: SimpleOptions | None = None,
    ) -> AssistantMessage:
        """等待通用参数调用的最终消息，不另发一次请求。"""
        return await self.stream_simple(model, context, options).result()

    async def complete(
        self,
        model: Model,
        context: Context,
        options: RequestOptions | None = None,
    ) -> AssistantMessage:
        """等待协议专用调用的最终消息。"""
        return await self.stream(model, context, options).result()

    async def aclose(self):
        """关闭调用者取消等待时，已经开始的资源清理仍完成。"""
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self):
        self._closed = True
        for controller in list(self._controllers.values()):
            controller.abort()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(*self._cleanup, return_exceptions=True)
        owned, self._owned = self._owned, {}
        try:
            await close_all(owned.values())
        except BaseException as exc:
            self._background_errors.append(exc)
        if self._background_errors:
            raise BaseExceptionGroup("Models cleanup failed", self._background_errors)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()
