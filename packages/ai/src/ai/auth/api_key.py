"""密钥、环境密钥与明确的免密认证。"""

from copy import deepcopy

from ai.auth.contracts import ModelAuth


class ApiKeyAuth:
    """选定凭据后不尝试其他账户；真实有效性由供应商判断。"""

    def __init__(self, env_var=None, *, keyless=False):
        self.env_var = env_var
        self.keyless = keyless

    async def resolve(self, model, store, context, override=None):
        if override is not None:
            return deepcopy(override)
        stored = await store.read(model.provider)
        if stored is not None:
            return stored
        key = context.get_env(self.env_var) if self.env_var else None
        if key:
            return ModelAuth(api_key=key)
        return ModelAuth() if self.keyless else None
