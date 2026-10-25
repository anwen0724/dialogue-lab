from ai.auth.api_key import ApiKeyAuth
from ai.auth.contracts import AuthContext, ModelAuth
from ai.auth.memory import MemoryCredentialStore
from ai.models import Models
from ai.testing.fake_provider import FakeProvider
from ai.types.model import Model


async def test_explicit_auth_then_store_then_environment_without_account_fallback():
    model = Model("example", "model", "api", "https://unused")
    store = MemoryCredentialStore()
    resolver = ApiKeyAuth("TEST_KEY")
    context = AuthContext({"TEST_KEY": "environment"})
    assert (await resolver.resolve(model, store, context)).api_key == "environment"
    await store.modify("example", lambda old: ModelAuth("stored"))
    assert (await resolver.resolve(model, store, context)).api_key == "stored"
    assert (
        await resolver.resolve(model, store, context, ModelAuth("explicit"))
    ).api_key == "explicit"
    assert await store.list() == ("example",)
    await store.delete("example")
    assert await resolver.resolve(model, store, AuthContext({})) is None
    assert await ApiKeyAuth(keyless=True).resolve(model, store, AuthContext({})) == ModelAuth()


async def test_registry_filters_by_auth_without_probing_and_custom_model_is_not_whitelisted():
    model = Model("fake", "known", "fake", "http://unused")
    provider = FakeProvider(models=[model])
    provider.auth = ApiKeyAuth("TEST_KEY")
    store = MemoryCredentialStore()
    async with Models(store, AuthContext({})) as models:
        models.set_provider(provider)
        assert models.get_models() == (model,)
        assert models.get_model("fake", "known") == model
        assert models.get_provider("missing") is None
        assert await models.get_available_models() == ()
        await store.modify("fake", lambda old: ModelAuth("stored"))
        assert await models.get_available_models() == (model,)
        assert not provider.started.is_set()
        custom = Model("fake", "custom", "fake", "http://unused")
        from ai.types.messages import Context

        assert (await models.complete_simple(custom, Context())).stop_reason == "stop"
        models.delete_provider("fake")
        assert models.get_models() == ()
        assert (await store.read("fake")).api_key == "stored"
