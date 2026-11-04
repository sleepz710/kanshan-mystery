# 看山谜案馆

和 AI 角色对话，把证据连成真相。看山谜案馆是一座多智能体推理剧场：玩家问话、出示证据、拆穿谎话，在角色对质中重建事件经过。比赛高级组参赛作品，主题为 AI 陪伴交互。

招牌案件《一笔消失的学费》从两万元学费失踪开始，包含四个角色、十二条线索、五句谎话与三个结局。刘看山是玩家的调查搭档，每局提供五次是非问答，并按调查进度给出提示。

进度见 [docs/STATUS.md](docs/STATUS.md)，分工见 [TASKS.md](TASKS.md)。作品介绍、海报和视频录制稿见 [比赛提交材料](docs/submission/README.md)。

## 当前进度

进度和已定的决定以 [docs/STATUS.md](docs/STATUS.md) 为准。真实模型数据见 [评测报告](eval/results/2026-11-02/README.md)。

## 快速运行

需要 Python 3.11+。首次获取代码：

```bash
git clone https://github.com/sleepz710/kanshan-mystery.git
cd kanshan-mystery
```

### Windows / PowerShell

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
# 仅首次创建；已有 .env 时保留原文件，按 .env.example 补齐变量
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn backend.app:app --reload
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 仅首次创建；已有 .env 时保留原文件，按 .env.example 补齐变量
cp .env.example .env
.venv/bin/python -m uvicorn backend.app:app --reload
```

配置样例默认 `LLM_MOCK=1`，无需模型密钥。打开 [接口文档](http://127.0.0.1:8000/docs)，先调用 `POST /api/games`，请求体为 `{"story_id":"lost-tuition"}`；再将返回的 `game_id` 用于对话、出示证据和提交推理接口。模拟回复固定，用于开发联调。

接真实模型时，在 `.env` 将 `LLM_MOCK` 改为 `0`，填写 `LLM_API_KEY` 和对应模型配置；完整变量说明见下方「本地运行与更新」一节，样例见 [.env.example](.env.example)。修改配置后重启服务，进程环境变量优先于 `.env`。

Windows 运行测试：`.venv\Scripts\python.exe -m pytest`；macOS / Linux 使用 `.venv/bin/python -m pytest`。自动测试隔离本地密钥并使用模拟客户端。

## 智能体如何协作

| 模块 | 职责 |
|---|---|
| 世界引擎 | 保存 YAML 事实与局内状态，计算信任、拆穿条件、事件、结局和评级 |
| 角色智能体 | 使用各自获准的事实、当前谎话和本角色对话历史回应玩家 |
| 核查智能体 | 检查回复的越界和矛盾，未通过时要求重写一次 |
| 刘看山 | 回答「是／不是／不重要」；引擎按阶段发放调查提示 |
| 编剧与检查器 | 按玩家素材改编剧本，检查引用、线索可达性与可解性；生成入口待合入 |

后端使用 FastAPI，前端采用原生 HTML/CSS/JavaScript。演员与编剧可分别配置 OpenAI 兼容模型服务。

## 目录

| 路径 | 内容 |
|---|---|
| `AGENTS.md` | 所有 AI 编程助手共用的规则(Codex 等工具会自动读取) |
| `CLAUDE.md` | 让 Claude Code 读取 AGENTS.md |
| `SPEC.md` | 范围、接口、技术栈 |
| `TASKS.md` | 任务清单和交接 |
| `docs/STATUS.md` | 项目进度、已定和待定事项 |
| `docs/assignment.md` | 比赛主题与评分标准 |
| `docs/ideas.md` | 选题过程记录 |
| `docs/story-v2.md` | 招牌案件的完整故事,含汤底 |
| `docs/g-mystery-draft.md` | 第一版的多智能体设计草案 |
| `docs/assets/` | 图片等素材 |
| `docs/submission/` | 作品信息、海报、视频脚本、字幕和 B 站发布文案 |
| `backend/` | 游戏引擎、接口、智能体与剧本检查器 |
| `stories/` | 招牌案件 YAML；调查路线含完整剧情答案 |
| `tests/` | 自动测试与固定样本 |
| `deploy/` | 本地启动与口令保护 |

## 怎么一起干活

1. 第一次:`git clone https://github.com/sleepz710/kanshan-mystery.git`。
2. 任务当面分好。在仓库目录里打开自己的 AI 助手(Codex、Claude Code),第一句说「做 TASKS.md 里的任务 02,按 AGENTS.md 的流程来」。不会自动读取 `AGENTS.md` 的工具,先让它去读。
3. agent 在任务分支上开发,做完自己开 Pull Request;在 GitHub 上看过改动后点合并。

## 本地运行与更新

### 本地体验（Windows，无需 Docker）

需要 Python 3.11+。在仓库根目录打开 PowerShell，首次创建 `.env`：

```powershell
Copy-Item .env.example .env
notepad .env
```

在 `.env` 保留 `LLM_MOCK=1`，追加体验账号和至少 12 位的口令，替换下面的示例值：

```dotenv
DEPLOY_USERNAME=judge
DEPLOY_PASSWORD=replace-with-your-own-password
```

启动会创建 `.venv`、安装依赖，并在后台启动一个服务进程：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/local.ps1 start
```

打开 <http://127.0.0.1:8000>，在浏览器弹窗输入账号和口令。页面、接口和 `/docs` 都需要认证；前端同源请求会使用浏览器保存的认证信息。联调 API 可打开 <http://127.0.0.1:8000/docs>。

```powershell
# 检查口令保护、首页和招牌案件开局；不调用模型
.venv\Scripts\python.exe deploy/smoke.py
# 查看状态、停止
powershell -ExecutionPolicy Bypass -File deploy/local.ps1 status
powershell -ExecutionPolicy Bypass -File deploy/local.ps1 stop
# 一条命令：拉取当前分支的上游更新、安装依赖、测试、重启
powershell -ExecutionPolicy Bypass -File deploy/local.ps1 update
```

日志在 `.cache/deploy/server.err.log` 和 `server.out.log`。更新前先提交代码改动，发布机使用 `main`；更新使用 `git pull --ff-only`，遇到分叉会停止。

`.env` 不随 Git 更新；已有部署请对照最新版 `.env.example` 补齐下面的模型配置，保留已有密钥和体验口令。启动、更新脚本从项目根目录运行，部署入口读取同一份 `.env`；进程环境变量优先。

| 变量 | 用途与填写方式 |
|---|---|
| `LLM_MOCK` | `1` 为模拟模式，无需密钥；真实模型改为 `0` |
| `LLM_BASE_URL` | 共用接口地址，默认 `https://api.deepseek.com` |
| `LLM_API_KEY` | 共用模型密钥，真实调用时填写 |
| `LLM_ACTOR_MODEL` | 演员模型，默认 `deepseek-flash` |
| `LLM_WRITER_MODEL` | 编剧模型，默认 `deepseek-flash`（开思考） |
| `LLM_WRITER_BASE_URL` | 编剧独立接口，留空使用共用地址 |
| `LLM_WRITER_API_KEY` | 编剧独立密钥，留空使用共用密钥 |

`LLM_MODEL` 是旧版演员模型的回退配置，`LLM_ACTOR_MODEL` 优先。切换到 OpenAI 等其他服务时，地址、密钥和对应模型名一起修改；编剧独立地址与密钥分别回退到共用值。DeepSeek 演员关闭思考、编剧开启思考由模型层处理。修改 `.env` 后，停止再启动服务让配置生效；更新脚本会重启，但不会覆盖 `.env`。

手机联调：先停止服务，再用 `start -BindAddress 0.0.0.0` 启动；电脑与手机连接同一 Wi-Fi，手机打开 `http://电脑的局域网IPv4:8000`。Windows 防火墙仅为该 Python 放行专用网络入站。这个 HTTP 地址只用于本机和可信局域网。使用自定义端口或监听地址时，更新也传入相同的 `-Port` / `-BindAddress`。

### 验收与已知问题

- 电脑、手机都要检查：输入口令、打开首页、招牌案件开局、对话、生成剧场生成并开局。`smoke.py` 自动检查口令、首页、API 文档、案件列表和第二版开局结构，不调用模型。
- 重启会清空进行中的对局、编剧对话和生成任务；更新前通知试玩人员。`data/stories/` 留在本机，更新不删除生成剧本。
