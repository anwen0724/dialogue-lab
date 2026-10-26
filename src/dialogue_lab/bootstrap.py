"""装配应用资源并维护单进程的 Session 控制权。"""

import asyncio
import os
from pathlib import Path

from ai import AuthContext, ModelAuth, Models, SimpleOptions
from ai.providers.anthropic import create_anthropic_provider
from ai.providers.deepseek import create_deepseek_provider
from ai.providers.openai import create_openai_provider
from dotenv import dotenv_values

from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.scheduler import Scheduler
from dialogue_lab.scenes.service import SceneService
from dialogue_lab.sessions.service import SessionService
from dialogue_lab.storage.compaction_store import CompactionStore
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.scene_store import SceneStore
from dialogue_lab.storage.session_store import SessionStore
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
        self.prompts = SystemPrompts(
            settings.prompts_directory,
            Path(__file__).parent / "resources" / "prompts",
            settings.data_directory / "prompts",
        )
        self.scenes = SceneService(SceneStore(self.database), self.prompts, settings.data_directory)
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
        model = self.models.get_model(self.settings.ai_provider, self.settings.ai_model)
        if model is None:
            raise ValueError("配置的 AI 模型不在供应商目录中。")
        options = SimpleOptions(
            reasoning=self.settings.ai_reasoning,
            max_output_tokens=self.settings.ai_max_output_tokens,
            timeout=120,
            auth=ModelAuth(api_key=self.settings.ai_api_key.get_secret_value())
            if self.settings.ai_api_key.get_secret_value()
            else None,
        )
        context = ContextManager(self.sessions, self.models, model, self.prompts, self.compactions)
        scheduler = Scheduler(
            session_id,
            self.sessions,
            context,
            self.models,
            model,
            emit,
            options=options,
            synthesis_factory=lambda: Synthesis(
                api_key=self.settings.tts_api_key.get_secret_value()
                or self.settings.stt_api_key.get_secret_value(),
                model=self.settings.tts_model,
                voice=self.settings.tts_voice,
            ),
        )
        self.controllers[session_id] = scheduler
        return scheduler

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
