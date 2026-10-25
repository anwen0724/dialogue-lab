"""接收网页音频与控制事件，向网页交付识别结果。"""

import json
import logging
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dialogue_lab.voice.recognition import Recognition, VoiceInputError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/voice/input")
async def voice_input(socket: WebSocket) -> None:
    """一次连接对应一次连续语音输入，不创建持久化会话。"""
    origin = socket.headers.get("origin")
    if origin is not None:
        try:
            source = urlsplit(origin)
            same_origin = source.scheme in (
                "http",
                "https",
            ) and source.netloc == socket.headers.get("host")
        except ValueError:
            same_origin = False
        if not same_origin:
            await socket.close(code=1008)
            return
    await socket.accept()
    settings = socket.app.state.settings
    if not settings.stt_api_key.get_secret_value().strip():
        await socket.send_json(
            {
                "type": "error",
                "code": "STT_NOT_CONFIGURED",
                "message": "请在项目根目录的 .env 配置 DIALOGUE_LAB_STT_API_KEY 后重启后端。",
            }
        )
        await socket.close(code=1008)
        return
    try:
        async with Recognition(
            api_key=settings.stt_api_key.get_secret_value(), model=settings.stt_model
        ) as recognition:
            await socket.send_json({"type": "ready"})
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(receive_audio, socket, recognition)
                async for event in recognition.events():
                    await socket.send_json(event)
                # 尾句已排空，不再等待浏览器主动断开。
                tasks.cancel_scope.cancel()
        await socket.send_json({"type": "stopped"})
        await socket.close()
    except* WebSocketDisconnect:
        pass
    except* VoiceInputError as errors:
        await send_error(socket, first_voice_error(errors))
    except* Exception as errors:
        # 不输出异常全文，供应商异常可能携带鉴权信息或用户音频内容。
        logger.warning("语音输入失败，异常类型：%s", exception_names(errors))
        await send_error(
            socket, VoiceInputError("STT_FAILED", "无法完成语音识别，请检查语音配置和网络后重试。")
        )


def exception_names(error: BaseException) -> list[str]:
    """只保留排错所需的异常类型，不记录异常参数。"""
    if isinstance(error, BaseExceptionGroup):
        return [name for child in error.exceptions for name in exception_names(child)]
    return [type(error).__name__]


async def receive_audio(socket: WebSocket, recognition: Recognition) -> None:
    """输入串行递交；结束后仍监听断线，以便取消未完成识别。"""
    stopped = False
    while True:
        message = await socket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        audio = message.get("bytes")
        if audio is not None:
            if stopped or not audio or len(audio) % 2 or len(audio) > 32000:
                raise VoiceInputError("INVALID_AUDIO", "音频格式无效，请重新开始录音。")
            await recognition.feed_audio(audio)
        else:
            try:
                control = json.loads(message.get("text", ""))
            except (ValueError, TypeError):
                control = None
            if control != {"type": "stop"} or stopped:
                raise VoiceInputError("INVALID_CONTROL", "语音控制消息无效，请重新开始。")
            stopped = True
            await recognition.finish_input()


def first_voice_error(errors: BaseExceptionGroup) -> VoiceInputError:
    """AnyIO 会包装并发错误；只提取面向用户的错误，不泄露异常内容。"""
    error = errors.exceptions[0]
    return first_voice_error(error) if isinstance(error, BaseExceptionGroup) else error


async def send_error(socket: WebSocket, error: VoiceInputError) -> None:
    """连接仍可写时交付错误；断线时识别资源已由上下文管理器回收。"""
    try:
        await socket.send_json({"type": "error", "code": error.code, "message": error.message})
        await socket.close(code=1011)
    except (WebSocketDisconnect, RuntimeError):
        pass
