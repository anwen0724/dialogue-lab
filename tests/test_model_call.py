"""模型正文在结束前交付；实际模型调用仍经过 AI 包。"""

import asyncio

import pytest
from ai import AbortController, Context, SimpleOptions, UserMessage
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models

from dialogue_lab.runtime.model_call import call_model


@pytest.mark.asyncio
async def test_model_call_delivers_increments_and_final_message():
    models, model = make_models(ScriptedAdapter([["Hello", " there"]]))
    events = []

    async def emit(event):
        events.append(event)

    try:
        result = await call_model(
            models, model, Context(messages=[UserMessage("Hi")]), SimpleOptions(), emit
        )
        assert [event["text"] for event in events] == ["Hello", " there"]
        assert result.content[0].text == "Hello there"
        assert result.stop_reason == "stop"
    finally:
        await models.aclose()


@pytest.mark.asyncio
async def test_cancelled_model_call_returns_partial_message_for_saving():
    ready = asyncio.Event()

    class PausingAdapter(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            async for event in super().stream_simple(model, context, auth, options):
                if event.type == "done":
                    ready.set()
                    await asyncio.Event().wait()
                yield event

    models, model = make_models(PausingAdapter([["Partial"]]))
    controller = AbortController()
    events = []

    async def emit(event):
        events.append(event)

    try:
        task = asyncio.create_task(
            call_model(
                models,
                model,
                Context(messages=[UserMessage("Hi")]),
                SimpleOptions(signal=controller.signal),
                emit,
            )
        )
        await asyncio.wait_for(ready.wait(), 2)
        controller.abort()
        result = await asyncio.wait_for(task, 2)
        assert result.stop_reason == "aborted"
        assert result.content[0].text == "Partial"
    finally:
        await models.aclose()
