"""speechio 外部包边界的可控替身；应用协议和清理由真实应用执行。"""

from queue import Empty, Queue
from threading import Event
from types import SimpleNamespace


class SpeechSession:
    """提供录音时的临时结果和输入结束后的尾部结果。"""

    def __init__(self):
        self.events = Queue()
        self.closed = Event()
        self.pending_segments = 0

    def feed_audio(self, audio):
        self.pending_segments = 1
        self.events.put(self.event("realtime", "你好"))

    def end_input(self):
        if self.pending_segments:
            self.events.put(self.event("final", "你好，世界。"))
            self.events.put(self.event("completed"))

    def next_event(self, *, timeout):
        try:
            event = self.events.get(timeout=timeout)
        except Empty:
            return None
        if event.kind == "completed":
            self.pending_segments = 0
        return event

    def close(self):
        self.closed.set()

    @staticmethod
    def event(kind, text=""):
        return SimpleNamespace(
            kind=kind,
            turn=SimpleNamespace(turn_id=1),
            result=SimpleNamespace(text=text),
            error=None,
        )


class SpeechRuntime:
    """公开关闭结果用于证明应用不会遗留外部资源。"""

    def __init__(self):
        self.session = SpeechSession()
        self.closed = Event()

    def create_auto_session(self, **kwargs):
        return self.session

    def prepare(self):
        pass

    def close(self, *, timeout):
        self.closed.set()
        return SimpleNamespace(status="ok")
