# ai：独立异步模型调用库

本包组织模型调用，不管理业务 Session、选择上下文、执行工具或控制语音。导入名是 `ai`，分发名是 `dialogue-ai`。需要 Python 3.12 或更新版本。

## 1. 安装与独立运行

复制整个 `packages/ai/` 到任意项目后安装该目录即可使用。核心依赖只有 JSON Schema 校验组件，不要求后端、FastAPI、数据库或 speechio。

```powershell
uv pip install -e ./packages/ai
uv pip install -e './packages/ai[openai,anthropic]'
```

第一条只安装统一契约与测试 Provider。第二条同时安装两个官方 SDK。协议可选依赖分别是 `openai`、`anthropic`；缺少依赖时，构造对应适配器会给出安装提示。开发环境使用包内 `uv.lock` 锁定版本。

```powershell
cd packages/ai
uv sync --all-extras
uv run python examples/stream_text.py
uv run --all-extras pytest
uv run ruff check src tests examples
```

## 2. 公开调用

宿主传入 `Model`、`Context` 和选项。`Model` 的 `provider` 选择供应商，`api` 选择协议，`base_url` 是模型端点。供应商目录用于发现，不是调用白名单。

```python
from ai import Context, Models, SimpleOptions, UserMessage
from ai.providers.openai import create_openai_provider


async def reply(model_id: str):
    provider = create_openai_provider()
    async with Models() as models:
        models.set_provider(provider, owns_provider=True)
        model = models.get_model("openai", model_id)
        if model is None:
            raise ValueError(f"Unknown OpenAI model: {model_id}")
        stream = models.stream_simple(
            model,
            Context(system_prompt="简短回答。", messages=[UserMessage("你好")]),
            SimpleOptions(max_output_tokens=256),
        )
        async for event in stream:
            if event.type == "text_delta":
                print(event.delta, end="")
        return await stream.result()
```

示例读取 `OPENAI_API_KEY`。调用方传入内置模型 ID，例如 `await reply("gpt-6.1-sol")`。Anthropic 与 DeepSeek 的创建函数分别读取 `ANTHROPIC_API_KEY` 和 `DEEPSEEK_API_KEY`。创建 Provider 时，内置目录已经包含模型 ID、协议、能力和容量，空端点由创建函数填入。创建和查询目录均不发送网络请求，也不选择默认模型。

### 2.1 内置模型目录

| Provider ID | 模型 ID | 协议 |
| --- | --- | --- |
| `openai` | `gpt-6.1-sol`、`gpt-6-luna`、`gpt-6-astra` | `openai-responses` |
| `anthropic` | `claude-sonnet-5-5`、`claude-haiku-5-5`、`claude-opus-5-5`、`claude-fable-5-1` | `anthropic-messages` |
| `deepseek` | `deepseek-flash`、`deepseek-v4-pro` | `openai-completions` |

目录按 2026-10-25 的 [OpenAI 模型资料](https://developers.openai.com/api/docs/models)、[Anthropic 模型资料](https://platform.claude.com/docs/en/models/overview)和 [DeepSeek 模型资料](https://api-docs.deepseek.com/quick_start/pricing/)声明。目录是随包维护的静态配置，不会自动追踪供应商变化，也不表示账户已获得模型权限。

三个创建函数对 `models` 参数采用相同规则：省略或传 `None` 时使用内置目录；显式传入序列时，用该序列替换内置目录；传 `[]` 时保留空目录。`base_url=` 能覆盖内置模型的端点；自定义 Model 已填写的 `base_url` 优先于创建函数的端点。

```python
from ai import Model
from ai.providers.deepseek import create_deepseek_provider

provider = create_deepseek_provider()  # 已包含两个内置模型
custom = create_deepseek_provider(
    models=[
        Model("deepseek", "my-model", "openai-completions", ""),
    ]
)
```

`models.get_models("deepseek")` 返回已注册 Provider 的目录；`models.get_model("deepseek", "deepseek-flash")` 返回对应 Model，找不到时返回 `None`。调用前应处理找不到模型的情况。目录仍不是调用白名单，调用方也能直接传入完整的 Model。

内置描述不覆盖供应商的温度和默认思考强度。`reasoning_levels` 提供当前模型实际可选的强度：OpenAI 与 Anthropic 为 `low/medium/high/xhigh/max`，DeepSeek 为 `low/high/max`。应用读取该字段显示选项，不需要另写一份列表。DeepSeek 接受的 medium 等别名不重复列入选项。

支持关闭思考的模型还提供 `off`：GPT-6 Luna、Claude Haiku 5.5、DeepSeek Flash 和 DeepSeek V4 Pro。其余五个内置模型不提供 off。Sonnet 的 between_tools 仍允许工具间思考，不能当作完全关闭。

调用方选哪个档位，AI 层就发送哪个档位。例如，`SimpleOptions(reasoning="max")` 会使用 max。传入不在模型选项中的档位时，返回错误消息，不发请求。切换模型后的界面选择由应用管理，AI 层不会自动改档。

`SimpleOptions(reasoning="off")` 明确关闭思考。省略 reasoning 则采用 Model 默认值；内置模型没有预设强度，因此交给供应商采用默认行为。`None` 与 off 不等价，不需要用 Hook 才能关闭。

```python
options = SimpleOptions(reasoning="off")  # 明确关闭；模型必须提供 off
options = SimpleOptions(reasoning="max")  # 明确使用 max
options = SimpleOptions()  # 使用默认设置，不表示关闭
```

Anthropic 内置模型在选择强度时使用自适应推理。内置 `cost` 保持 `None`，本包不把有条件的价格简化为固定费率。

### 2.2 调用入口

| 入口 | 选项 | 结果 |
| --- | --- | --- |
| `stream_simple` | `SimpleOptions` | `AssistantMessageStream` |
| `complete_simple` | `SimpleOptions` | await 后得到 `AssistantMessage` |
| `stream` | 对应协议 Options | `AssistantMessageStream` |
| `complete` | 对应协议 Options | await 后得到 `AssistantMessage` |

供应商失败返回 `stop_reason="error"` 的消息，调用方应检查停止原因。入口类型错误、工具校验错误可以直接抛出。`stop`、`length`、`tool_use` 是成功终态；`error`、`aborted` 是错误终态。

## 3. 消息、工具与输入转换

`Context` 包含便捷 `system_prompt`、消息和工具。规范化后为 `TranscriptContext`。`SystemMessage` 表达追加指令、命名段设置或删除，以及工具移除和添加。当前三个协议发送本次有效系统状态和工具集合。

输入消息是 `UserMessage`、`AssistantMessage`、`SystemMessage`、`ToolResultMessage`。图片使用 `ImageContent(mime_type, data)`，`data` 是 base64 字符串；库不读取文件。工具调用使用 `ToolCall`，原始 JSON 与解析结果分别保留。未完成 JSON 不作为有效工具参数。

发送视图会跳过失败助手消息、补齐未提供的工具结果、替换目标不支持的图片，并去掉跨模型无效的推理签名。转换不改写输入。工具结果按 `tool_call_id` 关联，系统消息不会提前结束结果组。

`validate_tool_call(tool, call)` 严格校验 Draft 2020-12 Schema，不转换类型或填写默认值。Schema 引用只在本地解析，不联网加载。校验失败抛 `ToolValidationError`。工具执行始终由宿主完成。

`convert_tool_call(tool, call, converter)` 只执行调用方明确提供的转换函数。该函数收到参数副本；结果仍须通过严格校验。原调用及原始 `arguments_json` 保留。库没有 null→0 等默认转换规则。

`message_to_dict` / `message_from_dict` 保留角色、块类型、错误、用量与重放元数据，不强制版本封套，也不承担数据库持久化。

## 4. 流、取消与关闭

调用 `stream*` 后立即启动生产，不等待消费。事件写入无容量上限的 FIFO；多个迭代器竞争同一个队列，不是广播。`result()` 独立等待最终消息，不消耗事件，可以重复读取。`partial` 是活动消息引用，需要历史状态时由调用方复制。

`break` 只停止消费。宿主持有 `AbortController`，通过 `options.signal=controller.signal` 传入请求，调用 `controller.abort()` 取消。流对象没有取消或关闭入口。取消正在等待 `result()` 的宿主任务，不会取消底层生成。

`Models.aclose()` 停止接收新调用，取消自己的活动请求，并关闭拥有的资源。默认注册为借用；`owns_provider=True` 明确转移关闭责任。多个 Models 可以借用同一个 Provider 和 Store，由外部所有者保证共享资源覆盖全部使用期。

适配器创建的 SDK 客户端由适配器关闭。注入客户端默认借用；`owns_client=True` 才由适配器关闭。Provider 替换不影响已取得旧 Provider 的请求，旧请求结束后释放本集合拥有的旧对象。

一个资源关闭失败时，仍尝试关闭其余所属资源。`aclose()` 最后通过异常组报告释放失败；重复关闭等待同一次关闭流程。外部所有者不得在其他借用者仍使用资源时提前关闭。

## 5. 认证、参数与协议扩展

认证优先级：请求 `ModelAuth` 覆盖 → `CredentialStore` → Provider 环境变量。已选凭据失效不会切换账户。`ApiKeyAuth(keyless=True)` 明确允许免密服务；认证缺失返回 None，和空认证对象区分。

`MemoryCredentialStore` 提供 `read/list/modify/delete`。`modify` 在锁内同步执行读改写函数；返回和保存使用副本。宿主可实现 `CredentialStore` Protocol 连接自己的持久化。

`timeout` 的单位是秒，直接交给 SDK。省略时采用 SDK 默认值，不另加覆盖认证、重试和宿主处理的总预算。`max_retries` 默认 0，表示额外请求次数。重试仅覆盖连接建立失败和允许的拒绝状态；不重放已开始的流。`Retry-After` 优先，否则等待 1、2、4、8 秒，上限 8 秒。

`retry_assistant_call(call, max_attempts=..., should_retry=...)` 是显式整次生成辅助。`max_attempts` 包含初次调用；判断函数收到最终消息与从 1 开始的尝试次数。辅助不拼接尝试结果、不执行工具，也不自动应用于 Models 调用。

### 5.1 通用与专用选项

Simple 参数优先于 Model 默认值。reasoning 必须属于目标模型的 `reasoning_levels`，否则返回错误消息，并列出当前可选档位。AI 层不自动升档、降档或忽略设置。两处都未设置 reasoning 时，不向供应商指定强度；这不表示关闭思考。

off 由适配器转换为关闭指令：Responses 使用 `reasoning.effort="none"`，DeepSeek 和 Anthropic 使用 `thinking.type="disabled"`。关闭 DeepSeek 和 Anthropic 时不附带强度。选择 DeepSeek 强度时，同时发送 `thinking.type="enabled"`。`"none"` 是部分协议的原生值，Simple 接口用 `"off"` 表达关闭。

本库与 pi 的内部表达不同：pi 的 Agent 将 off 转成未设置 reasoning，适配器据此处理关闭；本库保留显式 off，直到协议转换时才变成关闭指令。这样保留“使用默认设置”和“明确关闭”的区别。

| 协议 | 专用选项与兼容配置 |
| --- | --- |
| Completions | `CompletionsOptions`：temperature、max_tokens、reasoning_effort。`CompletionsCompat`：最大输出字段、推理字段、用量事件、strict 支持和 thinking_format。thinking_format 默认 openai，DeepSeek 工厂设为 deepseek，用于转换 Simple 的开关指令。 |
| Responses | `ResponsesOptions`：temperature、max_output_tokens、reasoning_effort、reasoning_summary、store。store 默认 false；保存和重放加密推理 item。 |
| Anthropic | `AnthropicOptions`：max_tokens、temperature、thinking_budget、cache_system。`AnthropicCompat` 声明自适应推理和 strict 支持。 |

Anthropic 要求输出额度：来自请求、Model 默认值或 Model.max_output_tokens，均未知时明确失败。自适应推理模型把选中的强度写入 output_config.effort。预算式模型使用专用 thinking_budget；Simple 接口不再把等级换成预算。专用 thinking_budget 不自动调整，必须至少为 1024 且小于 max_tokens。

OpenAI 的 input 已包含缓存读，output 已包含 reasoning；这些子集不再加到 total。Anthropic 原 input_tokens 不含缓存读写，统一 input 加入已知缓存读写一次。未知 token 字段保持 None。

`context_window` 是容量元数据。库不添加未定义的 tokenizer 或估算截断规则；输入选择和压缩仍由宿主完成。服务端容量拒绝按请求失败返回。OpenAI 的拒答内容转换为可见的 TextContent，并保存同模型重放所需的协议标记。

### 5.2 请求 Hook 与诊断

Hook 可同步或异步，均在原请求路径等待完成。`transform_headers` 在 Models 合并头后执行；`on_payload` 在协议请求构造后执行；`on_response` 接收状态和头；`on_provider_stream_event` 接收解析后的协议事件字典。Hook 不暴露 SDK 对象，异常导致请求失败。

`on_response` 对每次已收到的 HTTP 响应执行，包括将被重试的错误响应。没有 HTTP 响应的连接失败不触发它。`on_payload` 可返回替换后的字典，扩展字段通过 SDK 的 `extra_body` 发送。

observer 接收不可变 `DiagnosticEvent`：start、first_event、first_text、end。elapsed 使用单调时钟、单位秒。end 包含停止原因、已知用量和错误码。只有实际非空文字才产生 first_text；纯工具结果没有首字指标。诊断不携带正文或密钥，异常只写日志，不改变模型结果。

## 6. 扩展和验证边界

`create_provider` 组合静态 Model 列表、AuthResolver 和 `api_id -> ApiAdapter`。自定义 Provider 实现公开 Protocol 即可，不要求继承类。新协议返回统一事件和终态，关闭自己拥有的传输资源；Models 不增加供应商名称分支。

离线协议测试运行真实官方 SDK，只替换 HTTP 边界。真实模型测试默认跳过；启用前明确设置 `AI_LIVE=1`、`AI_LIVE_PROVIDER`、`AI_LIVE_MODEL`、`AI_LIVE_API` 与相应密钥，然后执行 `uv run --all-extras pytest tests/integration -m live`。测试结果不输出密钥。

OAuth、动态目录、图像生成、分类、deferred、Codex 和登录 CLI 仍按架构的具体接入条件扩展，本包不提供返回“未实现”的占位入口。
