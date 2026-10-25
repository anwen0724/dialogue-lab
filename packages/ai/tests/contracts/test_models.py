import asyncio

import pytest

from ai.models import Models
from ai.testing.fake_provider import FakeProvider
from ai.types.messages import Context, UserMessage
from ai.types.model import Model
from ai.types.options import AbortController, SimpleOptions

MODEL = Model("fake", "sample", "fake", "http://unused")
CONTEXT = Context(messages=[UserMessage("hello")])


@pytest.mark.parametrize("method", ["stream", "stream_simple", "complete", "complete_simple"])
async def test_four_entries_use_one_generation_contract(method):
    provider = FakeProvider("你好")
    async with Models() as models:
        models.set_provider(provider)
        result = getattr(models, method)(MODEL, CONTEXT)
        if method.startswith("stream"):
            result = await result.result()
        else:
            result = await result
    assert result.content[0].text == "你好"
    assert result.stop_reason == "stop"


async def test_production_starts_without_consumption_and_result_keeps_fifo_events():
    gate = asyncio.Event()
    provider = FakeProvider("abc", gate=gate)
    async with Models() as models:
        models.set_provider(provider)
        stream = models.stream_simple(MODEL, CONTEXT)
        await asyncio.wait_for(provider.started.wait(), 1)
        gate.set()
        result = await stream.result()
        events = [event async for event in stream]
        assert await stream.result() is result
        assert [event.type for event in events] == [
            "start",
            "text_start",
            "text_delta",
            "text_delta",
            "text_delta",
            "text_end",
            "done",
        ]
        assert "".join(e.delta for e in events) == "abc"
        assert events[0].partial is result


async def test_signal_cancels_generation_and_finishes_result():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)
    controller = AbortController()
    models = Models()
    models.set_provider(provider)
    stream = models.stream_simple(MODEL, CONTEXT, SimpleOptions(signal=controller.signal))
    await asyncio.wait_for(provider.started.wait(), 1)
    controller.abort()
    try:
        result = await asyncio.wait_for(stream.result(), 1)
        assert result.stop_reason == "aborted"
        assert [e.type async for e in stream][-1] == "error"
    finally:
        gate.set()
        await models.aclose()


async def test_closing_borrower_does_not_close_shared_provider_but_owner_does():
    shared = FakeProvider("shared")
    borrower, owner = Models(), Models()
    borrower.set_provider(shared)
    owner.set_provider(shared, owns_provider=True)
    await borrower.aclose()
    assert not shared.closed
    message = await owner.complete_simple(MODEL, CONTEXT)
    assert message.content[0].text == "shared"
    await owner.aclose()
    assert shared.closed


async def test_close_cancels_own_active_requests_and_rejects_new_calls():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)
    models = Models()
    models.set_provider(provider)
    stream = models.stream_simple(MODEL, CONTEXT)
    await asyncio.wait_for(provider.started.wait(), 1)
    try:
        await asyncio.wait_for(models.aclose(), 1)
        assert (await stream.result()).stop_reason == "aborted"
        with pytest.raises(RuntimeError):
            models.stream_simple(MODEL, CONTEXT)
    finally:
        gate.set()


async def test_replacement_keeps_old_call_and_releases_old_owned_provider_afterwards():
    gate = asyncio.Event()
    old = FakeProvider("old", gate=gate)
    new = FakeProvider("new")
    async with Models() as models:
        models.set_provider(old, owns_provider=True)
        stream = models.stream_simple(MODEL, CONTEXT)
        await asyncio.wait_for(old.started.wait(), 1)
        models.set_provider(new)
        assert (await models.complete_simple(MODEL, CONTEXT)).content[0].text == "new"
        assert not old.closed
        gate.set()
        assert (await stream.result()).content[0].text == "old"
        # 释放通过公开 close 状态观察，不依赖内部任务的数量或布局。
        await asyncio.wait_for(old.released.wait(), 1)
        assert old.closed


async def test_close_interrupts_waiting_start_observer():
    observing, release = asyncio.Event(), asyncio.Event()

    async def observer(event):
        if event.type == "start":
            observing.set()
            await release.wait()

    models = Models()
    models.set_provider(FakeProvider())
    stream = models.stream_simple(MODEL, CONTEXT, SimpleOptions(observer=observer))
    await asyncio.wait_for(observing.wait(), 1)
    try:
        await asyncio.wait_for(models.aclose(), 1)
        assert (await stream.result()).stop_reason == "aborted"
    finally:
        release.set()


async def test_resource_close_failure_does_not_skip_other_owned_resources():
    class FailingProvider(FakeProvider):
        async def aclose(self):
            raise OSError("release failed")

    failing = FailingProvider(id="failing")
    healthy = FakeProvider(id="healthy")
    models = Models()
    models.set_provider(failing, owns_provider=True)
    models.set_provider(healthy, owns_provider=True)
    with pytest.raises(ExceptionGroup):
        await models.aclose()
    assert healthy.closed


async def test_cancelled_result_waiter_does_not_cancel_generation():
    gate, waiting = asyncio.Event(), asyncio.Event()
    provider = FakeProvider("continued", gate=gate)
    async with Models() as models:
        models.set_provider(provider)
        stream = models.stream_simple(MODEL, CONTEXT)
        await asyncio.wait_for(provider.started.wait(), 1)

        async def wait_for_result():
            waiting.set()
            return await stream.result()

        waiter = asyncio.create_task(wait_for_result())
        await waiting.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        gate.set()
        assert (await stream.result()).content[0].text == "continued"


async def test_break_consumption_does_not_cancel_active_generation():
    paused, resume = asyncio.Event(), asyncio.Event()

    class PausedProvider(FakeProvider):
        async def stream(self, model, context, auth, options):
            async for event in super().stream(model, context, auth, options):
                yield event
                if event.type == "text_start":
                    paused.set()
                    await resume.wait()

    async with Models() as models:
        models.set_provider(PausedProvider("continued"))
        stream = models.stream_simple(MODEL, CONTEXT)
        await asyncio.wait_for(paused.wait(), 1)
        async for _ in stream:
            break
        resume.set()
        result = await stream.result()
        assert result.content[0].text == "continued"
        assert result.stop_reason == "stop"
