"""仅替换 speechio 包边界，验证应用异步输入与音频排空。"""

import asyncio
from queue import Queue

import pytest
import speechio

from dialogue_lab.voice.synthesis import Synthesis


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

        def __iter__(self):
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
        audio = synthesis.audio()
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
