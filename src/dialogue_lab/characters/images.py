"""上传图片的真实文件边界：限制体积、验证解码、生成受控资源引用。"""

import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from dialogue_lab.sessions.types import SessionError

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def copy_image(directory, reference):
    """复制角色引用的本地图片，副本获得独立文件，不共享删除生命周期。"""
    if re.fullmatch(r"/api/media/[a-f0-9]{32}\.(jpg|png|webp)", reference):
        source = directory / reference.rsplit("/", 1)[1]
    elif reference in {
        "/api/scene-assets/cafe.png",
        "/api/scene-assets/studio.jpg",
        "/api/scene-assets/night.jpg",
    }:
        source = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "images"
            / reference.rsplit("/", 1)[1]
        )
    else:
        raise SessionError("IMAGE_NOT_FOUND", "角色图片不存在，无法复制。", 404)
    try:
        return save_image(directory, source.read_bytes())
    except OSError as error:
        raise SessionError("IMAGE_COPY_FAILED", "角色图片无法复制，请检查文件后重试。") from error


def save_image(directory, content):
    if len(content) > MAX_IMAGE_BYTES:
        raise SessionError("IMAGE_TOO_LARGE", "图片不能超过 10 MB。", 413)
    try:
        with Image.open(BytesIO(content)) as image:
            extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(image.format)
            if extension is None or image.width * image.height > 40_000_000:
                raise ValueError("unsupported image")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise SessionError("INVALID_IMAGE", "请选择有效的 JPG、PNG 或 WebP 图片。", 422) from error
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}.{extension}"
    path.write_bytes(content)
    return path
