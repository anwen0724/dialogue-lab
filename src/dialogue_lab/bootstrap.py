"""装配应用资源并维护单进程的 Session 控制权。"""

import asyncio
import os
from pathlib import Path

from ai import AuthContext, Models, SimpleOptions
from ai.providers.anthropic import create_anthropic_provider
from ai.providers.deepseek import create_deepseek_provider
from ai.providers.openai import create_openai_provider
from dotenv import dotenv_values

from dialogue_lab.characters.service import CharacterService
from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.scheduler import Scheduler
from dialogue_lab.runtime.settings import ReplySettings
from dialogue_lab.sessions.service import SessionService
from dialogue_lab.settings.service import SettingsService
from dialogue_lab.storage.character_store import CharacterStore
from dialogue_lab.storage.compaction_store import CompactionStore
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.session_store import SessionStore
from dialogue_lab.voice.catalog import get_speech_model
from dialogue_lab.voice.synthesis import Synthesis


class Services:
    """应用拥有数据库和 Models；每个控制连接拥有一个调度器。"""

    def __init__(self, settings):
        self.settings = settings
        self.database = Database(settings.database_url.get_secret_value())
        self.sessions = SessionService(SessionStore(self.database))
        self.compactions = CompactionStore(self.database)
        environment = {
            key: value
            for key, value in {
                **dotenv_values(settings.model_config["env_file"]),
                **os.environ,
            }.items()
            if value is not None
        }
        self.models = Models(auth_context=AuthContext(environment))
        for factory in (
            create_deepseek_provider,
            create_openai_provider,
            create_anthropic_provider,
        ):
            self.models.set_provider(factory(), owns_provider=True)
        self.application_settings = SettingsService(settings, self.models, environment)
        self.prompts = SystemPrompts(
            settings.prompts_directory,
            Path(__file__).parent / "resources" / "prompts",
            settings.data_directory / "prompts",
        )
        self.characters = CharacterService(
            CharacterStore(self.database),
            self.prompts,
            settings.data_directory,
            self.application_settings,
        )
        self.controllers = {}
        self._recovery_lock = asyncio.Lock()
        self._recovered = False

    async def claim(self, session_id, emit):
        """先恢复上次进程中断的压缩，再分配本进程唯一控制连接。"""
        async with self._recovery_lock:
            if not self._recovered:
                await self.compactions.interrupt_unfinished()
                self._recovered = True
        if session_id in self.controllers:
            return None
        selected = self.application_settings.current.dialogue
        model = self.models.get_model(selected.provider_id, selected.model_id)
        if model is None:
            raise ValueError("配置的 AI 模型不在供应商目录中。")
        context = ContextManager(
            self.sessions,
            self.models,
            model,
            self.prompts,
            self.compactions,
            character_store=self.characters.store,
        )
        scheduler = Scheduler(
            session_id,
            self.sessions,
            context,
            self.models,
            model,
            emit,
            settings_loader=self.reply_settings,
        )
        self.controllers[session_id] = scheduler
        return scheduler

    async def reply_settings(self, session_id):
        """读取全局选择及角色音色；闭包只捕获本轮确定的值。"""
        selection = self.application_settings.current
        model = self.models.get_model(selection.dialogue.provider_id, selection.dialogue.model_id)
        options = SimpleOptions(
            reasoning=selection.dialogue.reasoning,
            max_output_tokens=min(
                self.settings.ai_max_output_tokens,
                model.max_output_tokens or self.settings.ai_max_output_tokens,
            ),
            timeout=120,
        )
        speech = get_speech_model("tts", selection.tts)
        character = await self.characters.store.find_for_session(session_id)
        # 无角色的旧会话保留原配置；角色音色为空时不能借用该值。
        voice = character["tts_voice"] if character is not None else self.settings.tts_voice
        key = self.application_settings.environment.get(speech.credential_env, "")
        if voice not in dict(speech.voices):
            notice = (
                "请在角色设置中重新选择人物声音，文字交流仍可继续。"
                if character is not None
                else "旧会话的音色与当前合成模型不兼容，请修改原音色配置。文字交流仍可继续。"
            )
            return ReplySettings(model, options, None, notice)
        if not key:
            return ReplySettings(
                model, options, None, f"请配置 {speech.credential_env}，文字交流仍可继续。"
            )
        return ReplySettings(
            model,
            options,
            lambda: Synthesis(
                provider=speech.provider_id,
                api_key=key,
                model=speech.model_id,
                voice=voice,
            ),
        )

    async def release(self, session_id, scheduler):
        if scheduler is not None and self.controllers.get(session_id) is scheduler:
            try:
                await scheduler.close()
            finally:
                self.controllers.pop(session_id, None)

    async def close(self):
        try:
            for session_id, scheduler in list(self.controllers.items()):
                await self.release(session_id, scheduler)
        finally:
            try:
                await self.models.aclose()
            finally:
                await self.database.close()
