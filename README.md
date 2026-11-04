# 看山谜案馆

和 AI 角色对话，把证据连成真相。看山谜案馆是一座多智能体推理剧场：玩家问话、出示证据、拆穿谎话，在角色对质中重建事件经过。比赛高级组参赛作品，主题为 AI 陪伴交互。

招牌案件《一笔消失的学费》从两万元学费失踪开始，有四个角色、十二条线索、五句谎话和三个结局。刘看山是玩家的调查搭档，每局回答五次是非问题，并按调查进度给提示。玩家也可以把一碗海龟汤、一段小说、一个网址或一句想法交给编剧，改编出一桩新案子来玩。

进度和已定的决定见 [docs/STATUS.md](docs/STATUS.md)，任务和交接见 [TASKS.md](TASKS.md)，作品介绍、海报和视频录制稿见 [比赛提交材料](docs/submission/README.md)。

## 怎么玩

1. 标题画面点「开始探案」，选「从已有剧场游玩」或「新建剧场」。
2. 调查时可以向每个角色问话、出示手里的证据。证据对上了，角色的谎话被拆穿，有时会触发两人对质。卡住时问刘看山一个是非题，或看他的阶段提示。
3. 查清后提交推理，进入对应结局，看评级、汤底和复盘。
4. 新建剧场：贴入素材(文字、txt / md 文件或网址)，点「交给编剧」。编剧会确认改编方式(没看过答案 / 看过答案 / 全新)，再问要快速还是精修。生成要几分钟，期间可以先玩别的案子，完成后新案子出现在「我的剧场」。

## 运行

### Windows 桌面版

需要 Python 3.11+ 和 Microsoft Edge WebView2 Runtime(Windows 10/11 一般已自带)。在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r desktop/requirements.txt
.venv\Scripts\python.exe -m desktop.main
```

首次打开进入「模型设置」：选择 DeepSeek 或 OpenAI，填写自己的 API key 和模型名称，点「测试连接」，保存后开始探案。窗口顶部的「应用」菜单可打开模型设置、返回首页或退出。

打包成不需要 Python 的程序：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1 -Python .venv\Scripts\python.exe
```

产物是 `dist\看山谜案馆\看山谜案馆.exe`，拷贝时带上整个 `看山谜案馆` 文件夹。

程序数据写在 `%APPDATA%\KanshanMystery\`：模型配置(key 在 `config.json`，请妥善保管)、生成的剧本、草稿、对局与编剧记录、窗口里的浏览器存储和日志。设置环境变量 `KANSHAN_DATA_DIR` 可改用别的目录。更新程序时替换程序文件夹，用户数据保留。

### 网页版(开发调试)

```powershell
git clone https://github.com/sleepz710/kanshan-mystery.git
cd kanshan-mystery
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn backend.app:app --reload
```

macOS / Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`，`Copy-Item` 换成 `cp`。打开 <http://127.0.0.1:8000> 就是标题画面，接口文档在 `/docs`。

`.env` 默认 `LLM_MOCK=1`，不调用模型，角色和编剧返回固定的模拟内容，用于开发联调。接真实模型时把 `LLM_MOCK` 改为 `0` 并填写下面的配置，改完重启服务；进程环境变量优先于 `.env`。

| 变量 | 用途与填写方式 |
|---|---|
| `LLM_MOCK` | `1` 为模拟模式，无需密钥；真实模型改为 `0` |
| `LLM_BASE_URL` | 共用接口地址，默认 `https://api.deepseek.com` |
| `LLM_API_KEY` | 共用模型密钥 |
| `LLM_ACTOR_MODEL` | 演员组模型，默认 `deepseek-flash`(关思考) |
| `LLM_WRITER_MODEL` | 编剧组模型，默认 `deepseek-flash`(开思考) |
| `LLM_WRITER_BASE_URL` | 编剧独立接口，留空使用共用地址 |
| `LLM_WRITER_API_KEY` | 编剧独立密钥，留空使用共用密钥 |

换成 OpenAI 等其他服务时，地址、密钥和对应的模型名一起改。`LLM_MODEL` 是旧版演员模型配置，`LLM_ACTOR_MODEL` 优先。

运行测试：`.venv\Scripts\python.exe -m pytest`。测试隔离本地密钥，使用模拟客户端。

`deploy/local.ps1` 可以在后台启动网页版并加访问口令：在 `.env` 里设 `DEPLOY_USERNAME` 和至少 12 位的 `DEPLOY_PASSWORD`，然后运行 `powershell -ExecutionPolicy Bypass -File deploy/local.ps1 start`(另有 `status`、`stop`、`update`)，日志在 `.cache/deploy/`。

## 智能体如何协作

| 模块 | 职责 |
|---|---|
| 世界引擎 | 保存剧本 YAML 里的事实和局内状态，计算信任、拆穿条件、事件、结局和评级；数字都由代码计算 |
| 角色智能体 | 每个角色只拿到自己获准的事实、当前的谎话和自己的对话历史 |
| 核查智能体 | 检查角色回复是否越界或前后矛盾，不通过就重写一次，仍不通过时角色按人设回避 |
| 刘看山 | 只答「是 / 不是 / 不重要」，每局五次；引擎按调查进度发放提示 |
| 编剧 | 和玩家聊素材，确认改编方式和快速 / 精修；开思考写推理设计稿：真相、时间线、人物的秘密与谎话、证据链 |
| 填表与审稿 | 演员组关思考，把设计稿填成游戏剧本；审稿只看设计稿，指出因果和证据上的缺口 |
| 剧本检查器 | 程序检查(引用、线索可达、结局覆盖)、好玩度检查(线索分布、解锁层数、交叉拆谎)、两次盲答检查可解性；有问题回到设计稿修订 |

快速档 600 秒内最多 3 轮；精修档 900 秒内最多 4 轮，第一轮同时写两份设计稿，挑问题少的那份。后端是 FastAPI，前端是原生 HTML/CSS/JavaScript，桌面版用 pywebview 打开独立窗口。模型默认 DeepSeek，也支持 OpenAI 兼容接口，演员和编剧可以分开配置。

## 评测

- 招牌案件：四个角色各 30 道刺探题，核查关闭时模型判泄密 4/120，开启后 0/117，另有 3 条回复被阻止显示，模型评分待人工复核。数据与口径见 [评测报告](eval/results/2026-11-02/README.md)。
- 生成流程：设计稿两步生成、快速 / 精修、桌面版的真实模型验收记录在 [docs/testing/](docs/testing/)。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/` | 世界引擎、接口、角色与核查、刘看山;`backend/studio/` 是编剧和剧本检查器 |
| `frontend/` | 首页(标题画面)、游戏页、结局页;`frontend/studio/` 是编剧对话页 |
| `desktop/` | 桌面版入口、模型设置页和打包脚本 |
| `stories/` | 招牌案件 YAML；调查路线含完整剧情答案 |
| `eval/` | 泄密评测、AI 试玩、批量生成样本的脚本和结果 |
| `tests/` | 自动测试与固定样本 |
| `deploy/` | 网页版的本地后台启动与口令保护 |
| `AGENTS.md` | 所有 AI 编程助手共用的规则 |
| `CLAUDE.md` | 让 Claude Code 读取 `AGENTS.md` |
| `SPEC.md` | 范围、接口、数据格式、技术栈 |
| `TASKS.md` | 任务清单和交接 |
| `docs/STATUS.md` | 项目进度、已定和待定事项 |
| `docs/assignment.md` | 比赛主题与评分标准 |
| `docs/story-v2.md` | 招牌案件的完整故事，含汤底 |
| `docs/design/` | 界面参考图 |
| `docs/testing/` | 各轮测试与真实模型验收记录 |
| `docs/submission/` | 作品信息、海报、视频脚本、字幕和 B 站发布文案 |
| `docs/ideas.md`、`docs/g-mystery-draft.md` | 选题过程和第一版设计草案 |

## 我们怎么用 AI 协作开发

团队四人，各用自己的 AI 编程助手(Codex、Claude Code)分工。`AGENTS.md` 是所有助手共用的规则，`SPEC.md` 定接口，`TASKS.md` 记任务和交接。

1. 任务当面分好。在仓库目录里打开自己的 AI 助手，第一句说「做 TASKS.md 里的任务 N，按 AGENTS.md 的流程来」。
2. 一个任务一个分支，agent 做完自己开 Pull Request，在 GitHub 上看过改动后合并。
3. 做完或额度快用完时，agent 在 `TASKS.md` 该任务的「进展」里写交接，下一位只看这里就能接着做。

## 已知问题

- 网页版的对局、编剧对话和生成任务保存在服务进程里，重启后清空；生成的剧本文件保留。桌面版重新打开会恢复本机的对局和编剧记录。
- 生成一个案子要几分钟。
