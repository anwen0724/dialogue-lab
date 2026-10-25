"""会话实时接入：一个连接协调命令、识别事件和回复输出。"""

import asyncio
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from dialogue_lab.runtime.events import Submit
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.voice.recognition import Recognition, VoiceInputError

router = APIRouter()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubmitCommand(Command):
    type: Literal["submit"]
    request_id: UUID
    text: str = Field(min_length=1, max_length=32000)
    preset: str = Field(min_length=1, max_length=100)


class RecordingCommand(Command):
    type: Literal["start_recording"]
    preset: str = Field(min_length=1, max_length=100)


class StopCommand(Command):
    type: Literal["stop_recording", "stop_reply"]


class PlaybackCommand(Command):
    type: Literal["playback_finished"]
    request_id: UUID


commands = TypeAdapter(
    Annotated[
        SubmitCommand | RecordingCommand | StopCommand | PlaybackCommand,
        Field(discriminator="type"),
    ]
)


@router.websocket("/sessions/{session_id}/realtime")
async def session_websocket(socket: WebSocket, session_id: int):
    origin = socket.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            allowed = parsed.scheme in ("http", "https") and parsed.netloc == socket.headers.get(
                "host"
            )
        except ValueError:
            allowed = False
        if not allowed:
            await socket.close(code=1008)
            return
    await socket.accept()
    connection = SessionConnection(socket, session_id)
    await connection.run()


class SessionConnection:
    """接入层拥有 socket；runtime 只向事件队列输出，不等待网络发送。"""

    def __init__(self, socket, session_id):
        self.socket, self.session_id = socket, session_id
        self.services = socket.app.state.services
        self.scheduler = None
        self.outgoing = asyncio.Queue()
        self.connected = True
        self.tasks = set()
        self.recognition = None
        self.recording_task = None
        self.stop_recording_requested = False

    async def emit(self, event):
        if self.connected:
            self.outgoing.put_nowait(event)

    async def run(self):
        writer = asyncio.create_task(self.write())
        try:
            await self.services.sessions.open(self.session_id)
            self.scheduler = await self.services.claim(self.session_id, self.emit)
            # 取得控制权后重读，补齐 HTTP 查询与建立连接之间保存的消息。
            current = await self.services.sessions.open(self.session_id)
            await self.emit(
                {
                    "type": "connected",
                    "session_id": str(self.session_id),
                    "can_control": self.scheduler is not None,
                    "messages": current["messages"],
                }
            )
            while True:
                packet = await self.socket.receive()
                if packet["type"] == "websocket.disconnect":
                    break
                if self.scheduler is None:
                    await self.emit(
                        {
                            "type": "error",
                            "code": "SESSION_CONTROL_CONFLICT",
                            "message": "此会话正在另一个窗口使用，本窗口只读。",
                        }
                    )
                else:
                    try:
                        if packet.get("bytes") is not None:
                            audio = packet["bytes"]
                            if (
                                self.recognition is None
                                or self.stop_recording_requested
                                or (not audio or len(audio) % 2 or len(audio) > 32000)
                            ):
                                raise SessionError(
                                    "INVALID_AUDIO", "音频输入无效，请重新开始录音。"
                                )
                            await self.recognition.feed_audio(audio)
                            continue
                        command = commands.validate_json(packet.get("text") or "")
                        if isinstance(command, SubmitCommand):
                            self.spawn(
                                self.scheduler.submit(
                                    Submit(command.request_id, command.text, command.preset)
                                ),
                                str(command.request_id),
                            )
                        elif command.type == "stop_reply":
                            self.spawn(self.scheduler.stop())
                        elif command.type == "playback_finished":
                            self.spawn(self.scheduler.playback_finished(str(command.request_id)))
                        elif isinstance(command, RecordingCommand):
                            if self.recording_task is not None:
                                raise SessionError("RECORDING_BUSY", "录音尚未结束。")
                            self.stop_recording_requested = False
                            self.recording_task = asyncio.create_task(self.record(command.preset))
                        elif command.type == "stop_recording":
                            self.stop_recording_requested = True
                            if self.recognition is not None:
                                await self.recognition.finish_input()
                    except ValidationError:
                        await self.emit(
                            {
                                "type": "error",
                                "code": "INVALID_COMMAND",
                                "message": "请求格式无效。",
                            }
                        )
                    except SessionError as error:
                        await self.emit(
                            {"type": "error", "code": error.code, "message": str(error)}
                        )
                        if error.code == "INVALID_AUDIO" and self.recording_task is not None:
                            self.recording_task.cancel()
                            await asyncio.gather(self.recording_task, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except SessionError as error:
            await self.socket.send_json(
                {"type": "error", "code": error.code, "message": str(error)}
            )
        finally:
            self.connected = False
            if self.recording_task is not None:
                self.recording_task.cancel()
                await asyncio.gather(self.recording_task, return_exceptions=True)
            await self.services.release(self.session_id, self.scheduler)
            await asyncio.gather(*self.tasks, return_exceptions=True)
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

    async def record(self, preset):
        """final 由服务端直接提交；临时结果仅用于展示，结束录音保留尾句。"""
        try:
            await asyncio.to_thread(self.services.prompts.load, preset)
            settings = self.services.settings
            key = settings.stt_api_key.get_secret_value()
            if not key:
                raise SessionError("STT_NOT_CONFIGURED", "请配置语音识别密钥后重启后端。")
            async with Recognition(api_key=key, model=settings.stt_model) as recognition:
                self.recognition = recognition
                if self.stop_recording_requested:
                    await recognition.finish_input()
                else:
                    await self.emit({"type": "recording_ready"})
                finalized = set()
                async for event in recognition.events():
                    if event["type"] == "final":
                        segment = event["segment_id"]
                        if segment in finalized:
                            continue
                        finalized.add(segment)
                        await self.emit(event)
                        if event["text"].strip():
                            self.spawn(
                                self.scheduler.submit(
                                    Submit(uuid4(), event["text"], preset, "voice")
                                )
                            )
                    else:
                        await self.emit(event)
        except (SessionError, VoiceInputError) as error:
            await self.emit({"type": "error", "code": error.code, "message": str(error)})
        except Exception:
            await self.emit(
                {
                    "type": "error",
                    "code": "STT_FAILED",
                    "message": "语音识别失败，请检查配置和网络。",
                }
            )
        finally:
            self.recognition = None
            self.recording_task = None
            await self.emit({"type": "recording_stopped"})

    async def write(self):
        while True:
            event = await self.outgoing.get()
            if event["type"] == "audio":
                await self.socket.send_bytes(UUID(event["request_id"]).bytes + event["data"])
            else:
                await self.socket.send_json(event)

    def spawn(self, operation, request_id=None):
        """提交等待在独立任务中完成，socket 仍能读取停止和断线。"""

        async def execute():
            try:
                await operation
            except Exception as error:
                await self.emit(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "code": error.code if isinstance(error, SessionError) else "REQUEST_FAILED",
                        "message": str(error)
                        if isinstance(error, SessionError)
                        else "请求处理失败。",
                    }
                )

        task = asyncio.create_task(execute())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
