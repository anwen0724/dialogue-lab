"""应用支持的流式语音目录；与已安装 speechio 的适配能力保持一致。"""

from dataclasses import dataclass

from dialogue_lab.sessions.types import SessionError


@dataclass(frozen=True)
class SpeechModel:
    provider_id: str
    model_id: str
    name: str
    kind: str
    credential_env: str
    voices: tuple[tuple[str, str], ...] = ()


# 官方音色参数区分大小写。目录核对来源见本次实施计划，不按名字推断兼容性。
SPEECH_MODELS = (
    SpeechModel(
        "bailian",
        "qwen-audio-3.1-asr-flash-streaming",
        "Qwen Audio 3.1 ASR Flash Streaming",
        "stt",
        "DASHSCOPE_API_KEY",
    ),
    SpeechModel(
        "bailian",
        "qwen-audio-3.1-tts-flash",
        "Qwen Audio 3.1 TTS Flash",
        "tts",
        "DASHSCOPE_API_KEY",
        (
            ("longanhuan_v3.1", "龙安欢"),
            ("longanlingxin_v3.1", "龙安灵心"),
            ("longanfengyue_v3.1", "龙安风悦"),
            ("xunanchuan_v3.1", "许南川"),
            ("yuxiaoyun_v3.1", "于小云 · 中文"),
            ("anmingyuan_v3.1", "安明远 · 中文"),
            ("Emily_v3.1", "Emily · 英式英语"),
            ("Eric_v3.1", "Eric · 英式英语"),
            ("Abby_v3.1", "Abby · 美式英语"),
            ("David_v3.1", "David · 美式英语"),
        ),
    ),
)


def get_speech_model(kind, selection):
    """仅返回应用能调用的模型；文件转写模型不出现在实时识别目录中。"""
    for model in SPEECH_MODELS:
        if (model.kind, model.provider_id, model.model_id) == (
            kind,
            selection.provider_id,
            selection.model_id,
        ):
            return model
    raise SessionError("SPEECH_MODEL_UNSUPPORTED", "所选语音模型尚未接入。", 422)
