"""角色资料与身份文档的保存入口；不负责组织模型上下文。"""

import asyncio
import re
from uuid import uuid4

from dialogue_lab.characters.images import copy_image, save_image
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.voice.catalog import get_speech_model


class CharacterService:
    def __init__(self, store, prompts, data_directory, application_settings):
        self.store, self.prompts = store, prompts
        self.application_settings = application_settings
        self.directory = data_directory / "prompts"
        self.images = data_directory / "images"

    async def list(self):
        return [self.view(row) for row in await self.store.list()]

    async def get(self, character_id):
        row = await self.store.get(character_id)
        return {
            **self.view(row),
            "system_prompt": await asyncio.to_thread(self.prompts.load, row["prompt_key"]),
        }

    async def prompt_key(self, character_id):
        """每轮输入读取当前身份文档标识，已有连接也能使用修改后的指令。"""
        return (await self.store.get(character_id))["prompt_key"]

    async def save(self, values, character_id=None):
        """先写完整正文，再切换数据库引用；正在进行的调用仍可读取旧文件。"""
        values = dict(values)
        if "tts_voice" in values:
            model = get_speech_model("tts", self.application_settings.current.tts)
            if values["tts_voice"] not in dict(model.voices):
                raise SessionError(
                    "VOICE_UNSUPPORTED", "该音色不支持当前 TTS 模型，请重新选择。", 422
                )
        content = values.pop("system_prompt", None)
        path = None
        if content is not None:
            key = "custom-" + uuid4().hex
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{key}.md"
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
            values["prompt_key"] = key
        try:
            row = await (
                self.store.create(values)
                if character_id is None
                else self.store.update(character_id, values)
            )
        except BaseException:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
        return await self.get(row["character_id"])

    async def upload(self, character_id, kind, content):
        previous = await self.store.get(character_id)
        path = await asyncio.to_thread(save_image, self.images, content)
        try:
            await self.store.update(character_id, {f"{kind}_image": f"/api/media/{path.name}"})
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self._remove_image(previous[f"{kind}_image"])
        return await self.get(character_id)

    async def copy(self, character_id):
        """复制当前资料与独立文件；不创建会话，不替换原角色已有的失配音色。"""
        source = await self.get(character_id)
        values = {key: source[key] for key in ("category", "character_name", "tts_voice")}
        values["name"] = source["name"][:196] + "（副本）"
        created = []
        try:
            for field in ("cover_image", "background_image"):
                if source[field]:
                    path = await asyncio.to_thread(copy_image, self.images, source[field])
                    created.append(path)
                    values[field] = f"/api/media/{path.name}"
            values["prompt_key"] = "custom-" + uuid4().hex
            self.directory.mkdir(parents=True, exist_ok=True)
            document = self.directory / f"{values['prompt_key']}.md"
            created.append(document)
            await asyncio.to_thread(document.write_text, source["system_prompt"], encoding="utf-8")
            # 文件全部就绪后一次写入角色记录，失败只清理本次新建文件。
            row = await self.store.create(values)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {**self.view(row), "system_prompt": source["system_prompt"]}

    async def delete(self, character_id):
        """有历史会话时保留身份与图片；硬删除只移除本角色自己的文件。"""
        status, row = await self.store.delete(character_id)
        if status == "deleted":
            for kind in ("cover_image", "background_image"):
                self._remove_image(row[kind])
            if re.fullmatch(r"custom-[a-f0-9]{32}", row["prompt_key"]):
                (self.directory / f"{row['prompt_key']}.md").unlink(missing_ok=True)
        return status

    def _remove_image(self, reference):
        if reference and re.fullmatch(r"/api/media/[a-f0-9]{32}\.(jpg|png|webp)", reference):
            (self.images / reference.rsplit("/", 1)[1]).unlink(missing_ok=True)

    def view(self, row):
        return {
            "character_id": str(row["character_id"]),
            "voice_available": self.voice_available(row["tts_voice"]),
            **{
                key: row[key]
                for key in (
                    "name",
                    "category",
                    "character_name",
                    "tts_voice",
                    "cover_image",
                    "background_image",
                    "status",
                )
            },
        }

    def voice_available(self, voice):
        """失配音色保留原值；界面和运行时使用同一兼容规则。"""
        return voice in dict(get_speech_model("tts", self.application_settings.current.tts).voices)
