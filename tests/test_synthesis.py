"""仅替换 speechio 包边界，验证应用异步输入与音频排空。"""

import asyncio
from queue import Queue

import pytest
import speechio
from ai import AbortController

from dialogue_lab.voice.output import stream_speech
from dialogue_lab.voice.synthesis import Synthesis


@pytest.mark.asyncio
async def test_speech_delivers_timing_updates_with_the_same_audio_stream(monkeypatch):
    """外部包返回句子起点与最终字时间；应用须交付它们，不能再只取音频。"""
    format = speechio.AudioFormat(sample_rate=24000)
    start = speechio.TextTiming(0, "你好。", 0)
    end = speechio.TextTiming(0, "你好。", 0, 0.5, (speechio.WordTiming("你好", 0, 0.4),))

    class PackageStream:
        def send_text(self, text):
            pass

        def finish_input(self):
            pass

        def __iter__(self):
            return iter([speechio.AudioChunk(b"\0\0", format)])

        def events(self):
            return iter([start, speechio.AudioChunk(b"\0\0", format), end])

        def close(self):
            return speechio.CloseResult()

        def cancel(self):
            pass

    class PackageSynthesizer:
        def __init__(self, config):
            pass

        def open_stream(self, *, options):
            assert options.text_timestamps == "word"
            return PackageStream()

        def close(self):
            return speechio.CloseResult()

    monkeypatch.setattr(speechio, "Synthesizer", PackageSynthesizer)
    texts = asyncio.Queue()
    texts.put_nowait("你好。")
    texts.put_nowait(None)
    received = []

    async def emit(event):
        received.append(event)

    await stream_speech(
        lambda: Synthesis(api_key="test", model="test", voice="test"),
        texts,
        AbortController().signal,
        emit,
    )
    timings = [event for event in received if event["type"] == "text_timing"]
    assert [(item["segment_index"], item["end_seconds"]) for item in timings] == [
        (0, None),
        (0, 0.5),
    ]
    assert list(timings[-1]["words"]) == [{"text": "你好", "start_seconds": 0, "end_seconds": 0.4}]
    assert [event["data"] for event in received if event["type"] == "audio"] == [b"\0\0"]
    assert received[-1]["type"] == "audio_finished"


@pytest.mark.asyncio
async def test_synthesis_streams_before_text_end_and_drains_tail(monkeypatch):
    class PackageStream:
        format = speechio.AudioFormat(sample_rate=24000, channels=1, sample_type="int16")

        def __init__(self):
            self.queue = Queue()

        def send_text(self, text):
            self.queue.put(speechio.AudioChunk(text.encode("utf-16le"), self.format))

        def finish_input(self):
            self.queue.put(None)

        def cancel(self):
            self.queue.put(None)

        def close(self):
            self.cancel()
            return speechio.CloseResult()

        def events(self):
            return iter(self.queue.get, None)

    stream = PackageStream()

    class PackageSynthesizer:
        def __init__(self, config):
            pass

        def open_stream(self, *, options):
            return stream

        def close(self):
            return speechio.CloseResult()

    monkeypatch.setattr(speechio, "Synthesizer", PackageSynthesizer)
    async with Synthesis(api_key="test", model="test", voice="test") as synthesis:
        audio = synthesis.events()
        await synthesis.send_text("Hi")
        first = await asyncio.wait_for(anext(audio), 2)
        assert first.data == "Hi".encode("utf-16le")
        await synthesis.send_text("tail")
        await synthesis.finish_input()
        rest = [chunk.data async for chunk in audio]
        assert rest == ["tail".encode("utf-16le")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_synthesis_reports_incomplete_cleanup_and_releases_owner(monkeypatch, status):
    released = []

    class PackageStream:
        def close(self):
            return speechio.CloseResult(status=status)

    class PackageSynthesizer:
        def __init__(self, config):
            pass

        def open_stream(self, *, options):
            return PackageStream()

        def close(self):
            released.append(True)
            return speechio.CloseResult()

    monkeypatch.setattr(speechio, "Synthesizer", PackageSynthesizer)
    with pytest.raises(RuntimeError, match="合成资源"):
        async with Synthesis(api_key="test", model="test", voice="test"):
            pass
    assert released == [True]
