"""场景资料与身份文档的保存入口；不负责组织模型上下文。"""

import asyncio
import re
from uuid import uuid4

from dialogue_lab.scenes.images import save_image


class SceneService:
    def __init__(self, store, prompts, data_directory):
        self.store, self.prompts = store, prompts
        self.directory = data_directory / "prompts"
        self.images = data_directory / "images"

    async def list(self):
        return [self.view(row) for row in await self.store.list()]

    async def get(self, scene_id):
        row = await self.store.get(scene_id)
        return {
            **self.view(row),
            "system_prompt": await asyncio.to_thread(self.prompts.load, row["prompt_key"]),
        }

    async def prompt_key(self, scene_id):
        """每轮输入读取当前身份文档标识，已有连接也能使用修改后的指令。"""
        return (await self.store.get(scene_id))["prompt_key"]

    async def save(self, values, scene_id=None):
        """先写完整正文，再切换数据库引用；正在进行的调用仍可读取旧文件。"""
        values = dict(values)
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
                if scene_id is None
                else self.store.update(scene_id, values)
            )
        except BaseException:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
        return await self.get(row["scene_id"])

    async def upload(self, scene_id, kind, content):
        previous = await self.store.get(scene_id)
        path = await asyncio.to_thread(save_image, self.images, content)
        try:
            await self.store.update(scene_id, {f"{kind}_image": f"/api/media/{path.name}"})
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self._remove_image(previous[f"{kind}_image"])
        return await self.get(scene_id)

    async def delete(self, scene_id):
        """有历史会话时保留身份与图片；硬删除只移除本场景自己的文件。"""
        status, row = await self.store.delete(scene_id)
        if status == "deleted":
            for kind in ("cover_image", "background_image"):
                self._remove_image(row[kind])
            if re.fullmatch(r"custom-[a-f0-9]{32}", row["prompt_key"]):
                (self.directory / f"{row['prompt_key']}.md").unlink(missing_ok=True)
        return status

    def _remove_image(self, reference):
        if reference and re.fullmatch(r"/api/media/[a-f0-9]{32}\.(jpg|png|webp)", reference):
            (self.images / reference.rsplit("/", 1)[1]).unlink(missing_ok=True)

    @staticmethod
    def view(row):
        return {
            "scene_id": str(row["scene_id"]),
            **{
                key: row[key]
                for key in (
                    "name",
                    "category",
                    "character_name",
                    "cover_image",
                    "background_image",
                    "status",
                )
            },
        }
