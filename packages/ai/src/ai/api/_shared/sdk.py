"""三个 SDK 协议共用的响应生命周期，不包含供应商判断。"""

import asyncio
from contextlib import aclosing, asynccontextmanager
from copy import deepcopy

from ai._internal.accumulator import Accumulator
from ai.api._shared.retry import open_response
from ai.errors import ErrorInfo, MissingDependencyError, error_from_exception
from ai.hooks import invoke


class SDKAdapter:
    """封装 SDK 生命周期；协议子类只构造请求和解释事件。"""

    sdk = "openai"

    def __init__(self, client=None, *, owns_client=False):
        if client is None:
            try:
                if self.sdk == "openai":
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(api_key="", max_retries=0)
                else:
                    from anthropic import AsyncAnthropic

                    client = AsyncAnthropic(api_key="", max_retries=0)
            except ImportError as exc:
                raise MissingDependencyError(f"Install dialogue-ai[{self.sdk}]") from exc
            owns_client = True
        self._client = client
        self._owns_client = owns_client

    async def stream(self, model, context, auth, options):
        accumulator = Accumulator(model)
        yield accumulator.event("start")
        try:
            async with aclosing(
                self._generate(model, context, auth, options, accumulator)
            ) as events:
                async for event in events:
                    yield event
        except asyncio.CancelledError:
            yield accumulator.fail(ErrorInfo("aborted", "Request aborted"), aborted=True)
        except Exception as exc:
            yield accumulator.fail(error_from_exception(exc))

    def stream_simple(self, model, context, auth, options):
        return self.stream(model, context, auth, options)

    @asynccontextmanager
    async def _events(self, model, auth, options, payload, path, required):
        replacement = await invoke(options.on_payload, payload)
        if replacement is not None:
            payload = replacement
        if self.sdk == "openai":
            from openai import omit
        else:
            from anthropic import omit
        # SDK 的 copy 会把空字符串当作“沿用旧密钥”；认证头在本次请求显式覆盖。
        headers = {"authorization": omit, "x-api-key": omit}
        if auth.api_key:
            if self.sdk == "openai":
                headers["authorization"] = f"Bearer {auth.api_key}"
            else:
                headers["x-api-key"] = auth.api_key
        headers.update({name.lower(): value for name, value in auth.headers.items()})
        canonical = {name.lower(): name for name in self._client.default_headers}
        canonical.update({"authorization": "Authorization", "x-api-key": "X-Api-Key"})
        headers = {canonical.get(name, name): value for name, value in headers.items()}
        client = self._client.with_options(
            api_key=auth.api_key or "unused-keyless-credential",
            base_url=auth.base_url or model.base_url,
            max_retries=0,
            set_default_headers={},
            set_default_query={},
        )
        endpoint = client
        for name in path:
            endpoint = getattr(endpoint, name)
        request = {"extra_headers": headers}
        if options.timeout is not None:
            request["timeout"] = options.timeout
        # extra_body 保留 Hook 加入的协议字段，而不要求 SDK 已声明该字段。
        kwargs = {key: payload[key] for key in required}
        kwargs.update(stream=True, extra_body=payload, **request)
        async with open_response(
            lambda: endpoint.with_streaming_response.create(**kwargs),
            options.max_retries,
            options.on_response,
        ) as response:
            upstream = await response.parse()

            async def iterate():
                async for chunk in upstream:
                    data = chunk.model_dump(exclude_none=True)
                    await invoke(options.on_provider_stream_event, deepcopy(data))
                    yield data

            async with aclosing(iterate()) as events:
                yield events

    async def aclose(self):
        if self._owns_client and self._client is not None:
            client, self._client = self._client, None
            await client.close()
