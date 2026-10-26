"""上传图片的真实文件边界：限制体积、验证解码、生成受控资源引用。"""

from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from dialogue_lab.sessions.types import SessionError

MAX_IMAGE_BYTES = 10 * 1024 * 1024


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
