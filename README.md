# Dialogue Lab

Dialogue Lab 是一个以语音交流为重点的 AI 对话练习应用，支持英语口语练习、模拟面试和日常交流。你可以通过说话或打字与 AI 对话，实时查看回复并听取语音，也可以重新打开已有会话继续交流。

应用在本地运行，会话和消息保存在本地 PostgreSQL 中。对话模型、语音识别和语音合成通过配置的供应商服务调用。

## 功能

- **自定义场景**：从场景卡片进入对话，编辑人物名字、身份指令、封面和背景；预设场景也可以直接修改。
- **沉浸式界面**：主画面显示人物背景、最新消息和随实际声音变化的音波，底部操作区按需浮出，会话、消息和设置分别在侧栏打开。
- **连续语音对话**：开启麦克风后，识别结果实时显示；确认的文字自动提交，AI 的回复以流式文字和语音返回。
- **文字与语音交互**：支持直接打字发送消息，也可以在录音期间使用文字输入。
- **会话保存**：创建和切换多个会话，刷新页面后恢复消息，继续此前的交流。
- **打断控制**：可开启或关闭打断。关闭后，回复生成和播放期间暂停收音，结束后继续；也可以随时手动停止回复。
- **主动开场**：新会话由模型根据场景身份生成开场并播放；重新打开已有会话不会重复开场或播放历史音频。
- **上下文组织与压缩**：结合系统指令和会话消息组织模型输入；长对话达到压缩条件时，使用摘要和近期消息继续交流，保留原始记录。
- **多供应商模型接入**：独立 AI 层支持 OpenAI、Anthropic 和 DeepSeek，可通过配置选择供应商与模型。

## 系统组成

浏览器负责录音、消息展示和语音播放。后端通过 WebSocket 接收输入并返回文字和音频，通过 HTTP 提供场景管理、图片上传和会话创建与查询。

| 模块 | 职责 |
| --- | --- |
| 场景管理 | 保存场景资料、身份文档和图片，管理场景创建、修改与归档 |
| 会话管理 | 管理 Session，保存和读取 UserMessage、AssistantMessage |
| 上下文管理 | 加载系统指令、组织有效消息、处理上下文预算与压缩，并转换为 AI 层输入 |
| runtime | 调度输入处理、上下文准备、模型调用和语音输出，协调取消与消息保存 |
| AI 层 | 提供统一模型调用接口，处理供应商协议与流式响应 |
| 语音模块 | 管理语音识别和合成 |
| 存储模块 | 通过 PostgreSQL 保存会话、消息和压缩记录 |

场景身份正文保存在服务端文档中，上下文管理在每次调用前加载。修改身份指令后，已有会话的后续调用也使用新内容。会话不保存身份正文副本。

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、浏览器 Web Audio / AudioWorklet |
| 后端 | Python 3.12、FastAPI、Uvicorn |
| 数据存储 | PostgreSQL 17、SQLAlchemy、asyncpg、Alembic |
| 依赖与环境 | uv、npm、Docker Compose |

## 快速开始

以下命令使用 PowerShell。开发入口在一个终端中启动前后端，数据库由 Docker Compose 管理。

### 1. 准备环境

安装 Docker Desktop、uv，以及 Node.js 22.12+（22 系列）或 Node.js 24+ 和 npm。启动 Docker Desktop。Python 使用 3.12，uv 可下载所需解释器；本机不需要单独安装 PostgreSQL。

### 2. 安装依赖

在项目根目录执行：

```powershell
uv sync --locked
```

安装前端依赖，然后返回项目根目录：

```powershell
cd frontend
npm ci
cd ..
```

### 3. 填写配置

在项目根目录执行以下命令。若已有 `.env`，直接编辑它，不要覆盖。

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写数据库密码、DeepSeek 密钥和百炼语音密钥：

```dotenv
POSTGRES_PASSWORD=替换为字母和数字组成的数据库密码
DIALOGUE_LAB_DATABASE_URL=postgresql+asyncpg://dialogue_lab:${POSTGRES_PASSWORD}@127.0.0.1:5432/dialogue_lab
DEEPSEEK_API_KEY=你的DeepSeek密钥
DASHSCOPE_API_KEY=你的百炼密钥
```

保留密码行在数据库连接地址行之前。百炼语音识别和合成都使用 `DASHSCOPE_API_KEY`。完整配置项见 [.env.example](.env.example)，密钥不要提交到 Git。

### 4. 初始化数据库

在项目根目录执行：

```powershell
docker compose up -d --wait postgres
uv run alembic upgrade head
```

数据库通过 `127.0.0.1:5432` 提供访问，数据保存在 Docker 命名卷 `dialogue-lab_postgres_data` 中。

### 5. 启动应用

启动 Docker Desktop 后，在项目根目录执行：

```powershell
uv run dialogue-lab dev
```

命令启动或复用现有数据库，只读检查数据库版本，然后启动 Uvicorn 和 Vite。前后端保留热更新，并在当前终端直接显示日志。端口被占用时停止启动，不关闭其他程序。

打开 <http://127.0.0.1:5173>。后端接口文档位于 <http://127.0.0.1:8000/docs>。

### 日常启动与停止

完成首次准备后，日常启动 Docker Desktop，再执行 `uv run dialogue-lab dev` 即可。

在当前终端按 `Ctrl+C` 停止前后端，数据库保持运行。需要停止数据库时，在项目根目录执行：

```powershell
docker compose stop
```

普通停止不会删除会话数据。`docker compose down -v` 会删除数据卷，不用于日常停止。

### 更新数据库结构

首次初始化或更新代码后，如果启动器提示数据库版本不一致，在项目根目录手动执行：

```powershell
uv run alembic upgrade head
uv run dialogue-lab dev
```

启动器不会自动迁移。版本检查发生在数据库启动之后，因此收到版本提示时数据库已经运行。迁移只应用尚未执行的版本；没有新迁移时不重复修改。可用 `uv run alembic current` 查看当前数据库版本。

### 单独启动服务

排查问题时，可以保留原来的启动方式。数据库就绪后，在根目录启动后端：

```powershell
uv run uvicorn dialogue_lab.main:app --reload --host 127.0.0.1 --port 8000
```

在另一个终端启动前端：

```powershell
cd frontend
npm run dev
```

单独启动时，各终端分别按 `Ctrl+C` 停止服务。

## 使用方式

1. 点击一个场景卡片，继续最近会话；没有会话时，应用创建会话并生成开场。
2. 鼠标移到画面底部，或在触屏上点击底部区域，展开录音、文字输入和停止按钮。
3. 点击“开始说话”并允许麦克风访问，或输入文字发送。“停止说话”关闭麦克风。
4. 右上角“会话”查看当前场景的会话并新建；“消息”查看完整记录并输入文字；“设置”调整打断、音量、字幕、暗度和场景背景。
5. 首页“新建场景”添加自己的场景；卡片编辑按钮修改场景资料和身份指令。

开启打断时，新的确认输入停止旧回复；临时识别文字不会触发停止。关闭打断时，新输入需等待本轮生成与播放结束；主动关闭麦克风后不会自动恢复。

每个场景可以有多个会话。删除已有会话的场景会归档并保留记录，可从“最近练习”重新打开；没有会话的场景直接删除。旧版本的独立会话也从“最近练习”打开。

同一会话同时只允许一个窗口控制实时输入，其他窗口可以读取消息。

## 模型与指令配置

首页“应用设置”选择对话供应商、模型、推理强度，以及语音识别和合成模型。DeepSeek、OpenAI、Anthropic 分别读取 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`。没有配置密钥的供应商会显示为不可选；配置密钥后重启后端。

首次启动从 `.env` 的模型选项初始化 `data/settings.json`；之后以该文件为准，界面保存无需重启。初始对话模型为 `deepseek-flash`。当前语音接入支持百炼 `qwen-audio-3.1-asr-flash-streaming` 和 `qwen-audio-3.1-tts-flash`，页面只展示已接入的模型。

进入场景后，在“设置 → 人物声音”选择音色，新建场景也需要选择音色。更换全局合成模型前，应用会列出音色不兼容的场景；保存后保留这些场景的原音色，暂停其语音播放，文字交流仍可继续。重新选择兼容音色后恢复语音。对话模型、推理强度、TTS 和音色在下一次回复生效，STT 在下一次开始录音时生效。

升级旧版时先执行 `uv run alembic upgrade head`，迁移会将旧 `DIALOGUE_LAB_TTS_VOICE` 回填到已有场景。旧通用密钥变量不再读取：将旧 AI 密钥移到当前对话供应商变量，将旧百炼 STT/TTS 密钥移到 `DASHSCOPE_API_KEY`。两个旧语音密钥不同的情况下，应明确选定一个可同时使用识别和合成的百炼密钥。

场景身份指令通过界面编辑，保存于 `data/prompts/`；上传图片保存于 `data/images/`。`data/` 不提交 Git，备份时应连同数据库一起保留。通过 `DIALOGUE_LAB_DATA_DIRECTORY` 可以指定数据目录。内置场景由数据库迁移初始化一次，不会覆盖用户修改。

没有场景归属的旧会话继续使用 [prompts/](prompts/) 下的系统指令，以及 `DIALOGUE_LAB_TTS_VOICE` 指定的原音色。场景会话不使用这个音色配置。环境配置变更后需要重启后端，指令正文变更不需要。

## 项目目录

```text
frontend/                 前端页面、会话交互、录音与播放
src/dialogue_lab/
  api/                    HTTP 与 WebSocket 接口
  scenes/                 场景资料与图片管理
  resources/              内置场景身份文档和图片
  sessions/               会话管理
  settings/               全局模型设置与可选目录
  context/                上下文管理
  runtime/                调度与模型调用
  voice/                  语音识别与合成接入
  storage/                数据库访问
  bootstrap.py            应用资源装配
  config.py               环境配置
  main.py                 FastAPI 入口
packages/ai/              独立 AI 包
prompts/                  旧独立会话的系统指令文档
data/                     应用设置、用户身份文档和图片，不提交 Git
migrations/               数据库迁移
tests/                    应用测试
compose.yaml              本地 Docker 服务
```
