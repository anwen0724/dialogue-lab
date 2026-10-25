# Dialogue Lab

Dialogue Lab 是一个支持语音和文字交流的 AI 应用。用户可以新建或打开会话，说话或打字后获得流式文字回复和语音播放。消息保存在 PostgreSQL 中，刷新后可以继续交流。

当前已接通会话管理、上下文管理、runtime 调度、独立 AI 层与 speechio。系统指令按本次选择从 `prompts/` 加载；上下文达到预算条件时生成摘要并保留近期原文。原始消息仍可读取。页面采用石墨灰主题。

## 技术栈与目录

前端使用 React、TypeScript 和 Vite。后端使用 Python 3.12、FastAPI、Uvicorn、Pydantic Settings、SQLAlchemy 异步接口、asyncpg 和 Alembic。依赖分别由 npm 和 uv 管理。

```text
frontend/src/
  pages/                    页面布局与功能组合
  features/sessions/        会话列表、创建和打开
  features/dialogue/        消息、提交和会话连接协调
  features/voice-input/     麦克风和 PCM Worklet
  features/voice-output/    音频队列、播放和停止
  shared/api/               HTTP 请求与边界解析
src/dialogue_lab/
  api/                      HTTP、会话 WebSocket
  sessions/                 会话与消息规则
  context/                  文档加载、路径投影、预算、压缩和 AI 输入转换
  runtime/                  调度、模型调用和输出协调
  voice/                    speechio 识别与合成生命周期
  storage/                  数据库、表映射和事务
  bootstrap.py              应用资源装配
  config.py                 环境配置
  main.py                   FastAPI 入口
migrations/                 Alembic 迁移
prompts/                    系统指令正文
packages/ai/                独立 AI 包
tests/                     应用测试
compose.yaml                本地 Docker 服务与数据卷
.env.example                配置示例
pyproject.toml / uv.lock     Python 依赖与锁文件
docs-local/                 本地设计及开发文档，Git 忽略
docs/                       用户手动维护
```

## 环境准备

本机需要 Docker Desktop、Node.js 22.12+（22 系列）或 Node.js 24+、npm 和 uv。PostgreSQL 在 Docker 中运行，本机无需单独安装。Python 固定为 3.12；uv 可下载所需解释器。下列命令使用 PowerShell。

在项目根目录安装后端依赖：

```powershell
uv sync --locked
```

uv 使用根目录 `.venv`，`uv run` 不要求先激活虚拟环境。speechio 通过相邻项目 `../speechio` 可编辑安装；另一台机器也需要提供该项目。AI 包通过 `packages/ai` 安装。

在另一个终端安装前端依赖：

```powershell
cd frontend
npm ci
```

### 配置与数据库

首次配置时复制 `.env.example` 为 `.env`。若已有 `.env`，只补充缺少的配置，不覆盖凭据。

```powershell
Copy-Item .env.example .env
```

首次启动前，修改 `.env` 中的 `POSTGRES_PASSWORD`，并填写模型和语音密钥：

```dotenv
POSTGRES_PASSWORD=替换为本地数据库密码
DIALOGUE_LAB_DATABASE_URL=postgresql+asyncpg://dialogue_lab:${POSTGRES_PASSWORD}@127.0.0.1:5432/dialogue_lab
DEEPSEEK_API_KEY=你的DeepSeek密钥
DIALOGUE_LAB_STT_API_KEY=你的百炼密钥
```

数据库密码使用字母和数字，避免连接 URL 的特殊字符编码。保留密码行在连接地址行之前，应用加载 `.env` 时会展开引用。若系统环境变量已设置同名配置，先核对其值；环境变量会覆盖 `.env`。

启动 Docker Desktop，在项目根目录执行：

```powershell
docker compose up -d --wait postgres
uv run alembic upgrade head
```

第一条命令等待 PostgreSQL 健康检查通过。首次使用空数据卷时，官方镜像创建 `dialogue_lab` 用户和同名数据库。第二条命令创建或升级业务表：`sessions`、`session_messages`、`session_entries`、`session_compactions`。主键为自增 bigint，`request_id` 为 UUID。

Compose 项目名为 `dialogue-lab`，数据库服务名为 `postgres`，容器名由 Compose 生成为 `dialogue-lab-postgres-1`。后续服务加入同一份 `compose.yaml`，统一归属此项目。

数据库只通过 `127.0.0.1:5432` 提供本机访问。数据卷 `dialogue-lab_postgres_data` 挂载到容器的 `/var/lib/postgresql/data`，由 Docker Desktop 管理，不存入 Git。重建容器时复用此数据卷，数据不会随容器删除。

### 数据库启停与备份

日常启动数据库执行 `docker compose up -d --wait postgres`。手动停止整个项目下的服务：

```powershell
docker compose stop
```

`restart: unless-stopped` 让 Docker 启动后恢复未被手动停止的服务。手动停止后需重新启动；退出 Docker Desktop 时数据库不可用。

查看状态和日志：

```powershell
docker compose ps
docker compose logs --tail 50 postgres
```

普通停机或重建容器不删除数据卷。`docker compose down -v` 会删除本项目的数据卷和会话数据，不用于日常停机。数据卷不是备份；升级或迁移前另存备份。

以下命令把备份保存到本机临时目录。采用容器内生成、`docker compose cp` 复制的方式，避免旧版 PowerShell 重定向二进制数据：

```powershell
$backupPath = Join-Path $env:TEMP ("dialogue-lab-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".dump")
docker compose exec -T postgres pg_dump -U dialogue_lab -d dialogue_lab -Fc -f /tmp/dialogue-lab.dump
docker compose cp postgres:/tmp/dialogue-lab.dump $backupPath
docker compose exec -T postgres rm /tmp/dialogue-lab.dump
```

需要长期保留时，将备份文件移到自己的备份目录。恢复时将文件复制到目标 PostgreSQL 容器，再用 `pg_restore` 导入空数据库。不要直接覆盖有日常数据的数据库。

`POSTGRES_PASSWORD` 只用于空数据卷的首次初始化。已有数据库改密需先在 PostgreSQL 中修改用户密码，再同步 `.env` 并重启后端；只修改 `.env` 不会修改已有数据库密码。

### 模型、语音与指令配置

默认对话模型为 DeepSeek 的 `deepseek-flash`。可用 `DIALOGUE_LAB_AI_PROVIDER` 和 `DIALOGUE_LAB_AI_MODEL` 选择内置目录中的供应商与模型。OpenAI、Anthropic 分别使用 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`。`DIALOGUE_LAB_AI_API_KEY` 可覆盖当前调用凭据。

默认识别模型为 `qwen-audio-3.1-asr-flash-streaming`，合成模型为 `qwen-audio-3.1-tts-flash`，音色为 `longanhuan_v3.1`。未单独填写 `DIALOGUE_LAB_TTS_API_KEY` 时，TTS 使用 STT 的百炼密钥。修改型号前，应确认 speechio 和对应服务均支持该模型及音色。

`DIALOGUE_LAB_AI_REASONING` 未设置时采用模型默认行为；可配置模型支持的档位，包括模型支持时的 `off`。不将空字符串写作“未设置”。`DIALOGUE_LAB_AI_MAX_OUTPUT_TOKENS` 默认 4096。

系统指令默认位于 `prompts/`，可通过 `DIALOGUE_LAB_PROMPTS_DIRECTORY` 指定目录。页面选项来自其中的 Markdown 文件名。修改文档后，下一次调用使用新正文，不改写旧消息。

环境变量优先于根目录 `.env`。配置变更需要重启后端；指令正文变更不需要。密钥仅由后端使用，不放入前端配置或提交到 Git。

## 启动与使用

先确认 Docker Desktop 与数据库已启动。在项目根目录启动后端：

```powershell
uv run uvicorn dialogue_lab.main:app --reload --host 127.0.0.1 --port 8000
```

在 `frontend` 目录的另一个终端启动前端：

```powershell
npm run dev
```

打开 <http://127.0.0.1:5173>，创建或选择会话。点击“开始说话”并允许麦克风访问；准备完成后开始交流。停顿产生的确认文字由后端直接提交，浏览器不会重复发送。也可以在消息框中打字发送。

“结束录音”停止麦克风并确认尾句，尾句仍会触发回复。“停止回复”停止当前模型、合成和播放，保留录音。确认新的输入会停止旧回复；临时识别文字不会触发停止。停止时已收到的部分回复会保存。

刷新后读取保存的消息，不自动重发请求或播放历史音频。同一会话同时只允许一个窗口控制实时输入；其他窗口可查看，重新打开可重新申请控制权。

系统指令选择仅用于本次输入，不与会话绑定。自动压缩期间，新输入等待压缩结束后处理。文字生成、语音合成、浏览器播放分别结束；合成或播放失败不会自动重试模型调用。

Vite 将 `/api` 的 HTTP 和 WebSocket 转发到 `127.0.0.1:8000`，会话连接使用 `/api/sessions/{session_id}/realtime`。端口由启动命令和 Vite 配置控制。后端 API 文档为 <http://127.0.0.1:8000/docs>。

浏览器需通过 localhost、127.0.0.1 或 HTTPS 使用 AudioWorklet。输入音频为 16 kHz 单声道 PCM16；输出按服务端声明的格式播放。

## 验证

应用测试使用隔离的真实 PostgreSQL。本次 Compose 只管理日常数据库，不创建测试服务。运行应用测试前，另行准备测试实例和名称以 `_test` 结尾的专用测试库。测试会清空其中的四张业务表，不得使用日常数据库。

在项目根目录配置测试连接并迁移：

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://测试用户:密码@127.0.0.1:55432/dialogue_test'
$env:DIALOGUE_LAB_DATABASE_URL=$env:TEST_DATABASE_URL
uv run alembic upgrade head
uv run pytest tests --basetemp=.pytest_cache/app-tests
Remove-Item Env:DIALOGUE_LAB_DATABASE_URL
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

`TEST_DATABASE_URL` 未配置时，测试默认连接 `127.0.0.1:55432/dialogue_test`，用户名及密码为 `dialogue_test`。上述移除环境变量的命令恢复从 `.env` 读取应用连接；若原先通过环境变量配置业务连接，应恢复原值。

在 `frontend` 执行：

```powershell
npm run test
npm run lint
npm run build
```

`npm run build` 包含 TypeScript 检查。后端自动化只在供应商或 speechio 边界使用替身；业务会话、上下文、调度和数据库运行真实实现。前端替换设备与网络边界，执行真实页面、连接和 PCM 逻辑。

本次已验证真实 STT → 模型 → TTS 链路、真实合成途中取消、两轮文字对话和刷新恢复。语音链路使用合成音频输入；真人麦克风、中英文交流体验、自然停顿和扬声器回声仍需用户验收。详细证据见 `docs-local/plans/persistent-voice-dialogue.md`。

## 运行边界

当前调度按单后端进程运行，不使用多 Uvicorn worker。同一进程内不同会话独立调度。进程崩溃可能丢失尚未形成结束结果的内存回复草稿，已提交消息仍在数据库中。

`GET /api/health` 只检查 HTTP 服务响应，不验证数据库或外部服务。`npm run preview` 预览前端构建并沿用 Vite 的 `/api` 代理。生产静态服务需另配同源 `/api` 代理、WebSocket 升级并保留 Host；当前没有生产部署配置。
