"""合并请求认证头，执行 Models 层请求头扩展。"""

from dataclasses import replace

from ai.hooks import invoke


async def prepare_auth(auth, model, options):
    """后出现的来源覆盖同名头，比较名称不区分大小写。"""
    headers = {}
    for source in (auth.headers, model.headers, options.headers):
        headers.update({key.lower(): value for key, value in source.items()})
    transformed = await invoke(options.transform_headers, dict(headers))
    if transformed is not None:
        headers = dict(transformed)
    return replace(auth, headers=headers)
