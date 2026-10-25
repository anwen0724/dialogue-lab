# Dialogue Lab

Dialogue Lab 是一个模拟对话 AI 应用，计划提供文字和语音交互。

当前已实现独立 AI 包，以及网页实时语音输入。网页通过麦克风采集音频，经 WebSocket 交给后端的 speechio，显示识别中的文字和最终用户消息。页面采用石墨灰主题。

本次语音输入还没有接入 AI 回复、语音播放或数据库。消息保留在当前页面内存中，刷新后清空。自动化验证已通过；真实百炼识别效果仍需配置凭据后验证。

## 技术栈与目录

前端使用 React、TypeScript 和 Vite。后端使用 Python 3.12、FastAPI、Uvicorn 和 Pydantic Settings。前端依赖通过 npm 管理，后端依赖通过 uv 管理。

```text
frontend/
  src/
    app/            应用入口
    pages/          页面与页面交互
    features/voice-input/  语音输入界面、连接、录音和 Worklet
    shared/api/     HTTP 请求与响应校验
    styles/         全局样式
  package-lock.json
src/dialogue_lab/
  api/              HTTP 与 WebSocket 路由
  voice/            speechio 识别装配、事件和资源生命周期
  config.py         环境配置
  main.py           FastAPI 应用装配
tests/              应用接口测试
packages/ai/        独立 AI 包
.env.example        本地配置示例
pyproject.toml      Python 项目与依赖配置
uv.lock             Python 依赖锁文件
docs-local/         本地设计与开发文档，Git 忽略
docs/               用户维护的提交文档
```

## 环境准备

本机需要 Node.js 22.12+（22 系列）或 Node.js 24+、npm 和 uv。后端固定使用 Python 3.12；如果本机缺少该版本，uv 在同步依赖时下载解释器。

以下命令使用 PowerShell。每组命令均注明执行目录。

### 安装后端依赖

在仓库根目录执行：

```powershell
uv sync --locked
```

uv 在项目根目录创建并使用 `.venv`，同时安装运行依赖和开发依赖。`uv run` 自动使用这个虚拟环境，不必先激活它。

当前 speechio 以可编辑本地包接入，路径为相对于项目根目录的 `../speechio`，即本机的 `C:/all/work/practice/speechio`。在另一台机器准备环境时，也需要提供这个相邻项目；当前锁文件不会自动改为安装同名远程包。云端识别使用包内置 VAD，不需要下载本地语音识别模型。

如果编辑器需要指定 Python 解释器，在 Windows 中选择 `.venv/Scripts/python.exe`。

### 安装前端依赖

在仓库根目录的另一个终端执行：

```powershell
cd frontend
npm ci
```

`package-lock.json` 和 `uv.lock` 记录依赖版本，均纳入 Git 管理。虚拟环境、`node_modules`、构建输出和本地 `.env` 不纳入 Git。

## 本地启动

### 启动后端

在项目根目录执行：

```powershell
uv run uvicorn dialogue_lab.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址为 <http://127.0.0.1:8000>，交互式 API 文档位于 <http://127.0.0.1:8000/docs>。

### 启动前端

在 `frontend` 目录的另一个终端执行：

```powershell
npm run dev
```

打开 <http://127.0.0.1:5173>。点击“开始说话”并允许麦克风权限。识别服务准备完成后，页面显示“正在听”。说话期间显示实时文字，停顿后生成一条用户消息。

点击“结束录音”后，麦克风停止采集，页面继续等待最后一句的识别结果，完成后恢复开始按钮。准备期间可以点击“取消准备”；断线或识别失败后可以再次开始，之前已确定的消息不会删除。

页面下方保留“服务连接检查”，可查看健康接口状态或重新检查。健康接口不验证语音密钥是否有效。

Vite 将 `/api` 的 HTTP 和 WebSocket 请求转发到 `http://127.0.0.1:8000`。识别连接使用 `/api/voice/input`，浏览器无需访问另一个源。Vite 使用固定端口 5173；如果端口被占用，启动会报错。

### 后端配置

默认配置可以启动应用和检查健康接口。要使用云端语音识别，在项目根目录准备本地配置：

```powershell
Copy-Item .env.example .env
```

如果 `.env` 已存在，直接编辑现有文件，不要覆盖其中的凭据。添加以下配置：

```dotenv
DIALOGUE_LAB_STT_API_KEY=填写你的百炼密钥
DIALOGUE_LAB_STT_MODEL=qwen-audio-3.1-asr-flash-streaming
```

模型名称默认就是上面的流式识别模型，只填密钥也可以。修改型号时必须使用 speechio 已适配、支持原生流式识别的型号。对话模型的密钥不等于百炼语音密钥。

密钥只在后端使用，不需要前端 `.env`。`DIALOGUE_LAB_APP_NAME` 设置 FastAPI 文档中的应用名称。系统环境变量优先于 `.env`。修改配置后重启后端。

浏览器使用 AudioWorklet，需在 localhost、127.0.0.1 或 HTTPS 下打开。输入音频为 16 kHz 单声道 PCM16，识别自动分段采用 speechio 默认策略。每段默认最长 30 秒，持续讲话到达段长后由 speechio 分段处理，不限制整个输入连接只能使用 30 秒。

服务监听地址、端口和热重载由启动命令控制。

## 验证

在项目根目录执行：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

在 `frontend` 目录执行：

```powershell
npm run lint
npm run test
npm run build
```

`npm run build` 先检查 TypeScript 类型，再生成 `frontend/dist`。如果只需要检查类型，执行 `npm run typecheck`。

启动后端后，可在 PowerShell 中直接检查健康接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`GET /api/health` 返回 HTTP 200 和 `{"status":"ok"}`。这个接口仅证明 HTTP 服务能够响应；它不检查数据库、模型供应商或语音服务。

前端测试验证真实 Worklet 处理代码的 PCM 分帧及尾部输出，并在浏览器设备和 WebSocket 边界使用替身，验证页面状态与消息。后端测试验证公开 WebSocket 协议，并用真实 speechio 与内置 VAD 完成静音输入装配检查。自动化测试不调用百炼识别服务，不能据此认定真实识别准确率或停顿效果达标。

真实联调时，连续说几句中文和英文，检查临时文字、停顿后的最终消息、结束前尾句，以及结束后麦克风释放。再检查拒绝麦克风权限、断开后端与重新开始。实现计划与证据保存在 `docs-local/plans/realtime-voice-input.md`。

## 构建与部署边界

`npm run preview` 可预览构建后的静态文件。Vite 预览服务器会沿用开发配置中的 `/api` 代理，因此检查连接仍需要启动后端。代理配置不会写入构建后的静态文件。

部署时，静态服务需要将同源的 `/api` 请求转发到后端，支持 WebSocket 升级并保留原始 Host。语音入口检查浏览器 Origin 与 Host 是否一致。当前尚未配置生产部署和数据库。
