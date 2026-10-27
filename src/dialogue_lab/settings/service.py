"""持久保存全局模型选择；完整文件写入成功后才发布新设置。"""

import json
import os

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.settings.types import ApplicationSettings
from dialogue_lab.voice.catalog import SPEECH_MODELS, get_speech_model


class SettingsService:
    def __init__(self, startup, models, environment):
        self.models, self.environment = models, environment
        self.path = startup.data_directory / "settings.json"
        if self.path.exists():
            self.current = ApplicationSettings.model_validate_json(self.path.read_text("utf-8"))
            self.validate(self.current)
        else:
            self.save(
                ApplicationSettings.model_validate(
                    {
                        "dialogue": {
                            "provider_id": startup.ai_provider,
                            "model_id": startup.ai_model,
                            "reasoning": startup.ai_reasoning,
                        },
                        "stt": {"provider_id": "bailian", "model_id": startup.stt_model},
                        "tts": {"provider_id": "bailian", "model_id": startup.tts_model},
                    }
                )
            )

    def save(self, selection):
        """单进程同步替换保证读取者只能看到完整的旧版或新版设置。"""
        self.validate(selection)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(selection.model_dump(), output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.current = selection
        return selection

    def validate(self, selection):
        """校验目录和原生推理档位；此处不要求凭据，启动时仍可进入配置界面。"""
        chosen = selection.dialogue
        model = self.models.get_model(chosen.provider_id, chosen.model_id)
        if model is None:
            raise SessionError("MODEL_UNSUPPORTED", "对话模型不在内置目录中。", 422)
        if chosen.reasoning is not None and chosen.reasoning not in model.reasoning_levels:
            raise SessionError("REASONING_UNSUPPORTED", "该模型不支持所选推理档位。", 422)
        for kind in ("stt", "tts"):
            get_speech_model(kind, getattr(selection, kind))

    async def update(self, selection):
        """用户保存时要求凭据存在；启动时允许未配置凭据，以便进入设置页。"""
        self.validate(selection)
        chosen = selection.dialogue
        model = self.models.get_model(chosen.provider_id, chosen.model_id)
        if await self.models.get_auth(model) is None:
            raise SessionError("MODEL_NOT_CONFIGURED", "请先配置该对话供应商的密钥。", 422)
        for kind in ("stt", "tts"):
            speech = get_speech_model(kind, getattr(selection, kind))
            if not self.environment.get(speech.credential_env):
                raise SessionError(
                    "SPEECH_NOT_CONFIGURED", f"请先配置 {speech.credential_env}。", 422
                )
        return self.save(selection)

    async def dialogue_models(self):
        return [
            {
                "provider_id": model.provider,
                "model_id": model.id,
                "name": model.name,
                "reasoning_levels": model.reasoning_levels,
                "available": await self.models.get_auth(model) is not None,
            }
            for model in self.models.get_models()
        ]

    def speech_models(self):
        return [
            {
                "provider_id": model.provider_id,
                "model_id": model.model_id,
                "name": model.name,
                "kind": model.kind,
                "credential_env": model.credential_env,
                "available": bool(self.environment.get(model.credential_env)),
            }
            for model in SPEECH_MODELS
        ]
