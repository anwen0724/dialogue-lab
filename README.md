# Dialogue Lab

Dialogue Lab 是一个模拟对话 AI 应用，计划提供文字和语音交互。

当前已建立前后端工程。首页调用后端健康接口，显示连接结果，并提供重新检查按钮。会话、上下文管理、runtime 调度、模型接入和语音功能尚未实现。

## 技术栈与目录

前端使用 React、TypeScript 和 Vite。后端使用 Python 3.12、FastAPI、Uvicorn 和 Pydantic Settings。前端依赖通过 npm 管理，后端依赖通过 uv 管理。

```text
frontend/
  src/
    app/            应用入口
    pages/          页面与页面交互
    shared/api/     HTTP 请求与响应校验
    styles/         全局样式
  package-lock.json
backend/
  src/dialogue_lab/
    api/            HTTP 路由
    config.py       环境配置
    main.py         FastAPI 应用装配
  tests/            接口测试
  .env.example      本地配置示例
  pyproject.toml
  uv.lock
docs-local/         本地设计与开发文档，Git 忽略
docs/               用户维护的提交文档
```

## 环境准备

本机需要 Node.js 22.12+（22 系列）或 Node.js 24+、npm 和 uv。后端固定使用 Python 3.12；如果本机缺少该版本，uv 在同步依赖时下载解释器。

以下命令使用 PowerShell。每组命令均注明执行目录。

### 安装后端依赖

在仓库根目录执行：

```powershell
cd backend
uv sync --locked
```

uv 创建并使用 `backend/.venv`，同时安装运行依赖和开发依赖。`uv run` 自动使用这个虚拟环境，不必先激活它。

如果编辑器需要指定 Python 解释器，在 Windows 中选择 `backend/.venv/Scripts/python.exe`。

### 安装前端依赖

在仓库根目录的另一个终端执行：

```powershell
cd frontend
npm ci
```

`package-lock.json` 和 `uv.lock` 记录依赖版本，均纳入 Git 管理。虚拟环境、`node_modules`、构建输出和本地 `.env` 不纳入 Git。

## 本地启动

### 启动后端

在 `backend` 目录执行：

```powershell
uv run uvicorn dialogue_lab.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址为 <http://127.0.0.1:8000>，交互式 API 文档位于 <http://127.0.0.1:8000/docs>。

### 启动前端

在 `frontend` 目录的另一个终端执行：

```powershell
npm run dev
```

打开 <http://127.0.0.1:5173>。首页先显示连接中，收到健康接口的有效响应后显示“前后端已连接”。请求失败、返回值不符合约定或等待超过 5 秒时，页面显示失败原因。点击“重新检查”可再次发起请求。

前端请求相对地址 `/api/health`。Vite 将开发环境的 `/api` 请求转发到 `http://127.0.0.1:8000`，所以当前不需要配置跨域响应头。Vite 使用固定端口 5173；如果端口被占用，启动会报错。

### 后端配置

默认配置可直接启动应用。如果需要修改应用名称，在 `backend` 目录创建本地配置：

```powershell
Copy-Item .env.example .env
```

如果 `.env` 已存在，直接编辑现有文件。`DIALOGUE_LAB_APP_NAME` 设置 FastAPI 文档中的应用名称。系统环境变量优先于 `.env`。修改配置后重启后端。

服务监听地址、端口和热重载由启动命令控制。

## 验证

在 `backend` 目录执行：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

在 `frontend` 目录执行：

```powershell
npm run lint
npm run build
```

`npm run build` 先检查 TypeScript 类型，再生成 `frontend/dist`。如果只需要检查类型，执行 `npm run typecheck`。

启动后端后，可在 PowerShell 中直接检查健康接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`GET /api/health` 返回 HTTP 200 和 `{"status":"ok"}`。这个接口仅证明 HTTP 服务能够响应；它不检查数据库、模型供应商或语音服务。

本地联调时，启动两个服务并打开首页，确认页面显示连接成功。停止后端后点击“重新检查”，应显示连接失败。重新启动后端并再次检查，应恢复连接成功。

## 构建与部署边界

`npm run preview` 可预览构建后的静态文件。Vite 预览服务器会沿用开发配置中的 `/api` 代理，因此检查连接仍需要启动后端。代理配置不会写入构建后的静态文件。

部署时，静态服务需要将同源的 `/api` 请求转发到后端。当前尚未配置生产部署、数据库或外部模型与语音服务。
