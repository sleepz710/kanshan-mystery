# 看山谜案馆

多智能体推理剧场:玩家和几个各怀秘密的 AI 角色对话、出示证据、拆穿谎话,查出真相。可以玩团队打磨的招牌案件,也可以把一碗海龟汤、一段小说或一个网址发给编剧智能体,当场生成一个新案子,还能出题发给朋友玩。比赛「高级组」参赛作品,主题 AI 陪伴交互,开发中。

进度和待办见 [docs/STATUS.md](docs/STATUS.md)。

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

## 怎么一起干活

1. 第一次:`git clone https://github.com/sleepz710/kanshan-mystery.git`。
2. 任务当面分好。在仓库目录里打开自己的 AI 助手(Codex、Claude Code),第一句说「做 TASKS.md 里的任务 02,按 AGENTS.md 的流程来」。不会自动读取 `AGENTS.md` 的工具,先让它去读。
3. agent 在任务分支上开发,做完自己开 Pull Request;在 GitHub 上看过改动后点合并。

## 部署与更新

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
| `LLM_WRITER_MODEL` | 编剧模型，默认 `deepseek-v4-pro` |
| `LLM_WRITER_BASE_URL` | 编剧独立接口，留空使用共用地址 |
| `LLM_WRITER_API_KEY` | 编剧独立密钥，留空使用共用密钥 |

`LLM_MODEL` 是旧版演员模型的回退配置，`LLM_ACTOR_MODEL` 优先。切换到 OpenAI 等其他服务时，地址、密钥和对应模型名一起修改；编剧独立地址与密钥分别回退到共用值。DeepSeek 演员关闭思考、编剧开启思考由模型层处理。修改 `.env` 后，停止再启动服务让配置生效；更新脚本会重启，但不会覆盖 `.env`。

手机联调：先停止服务，再用 `start -BindAddress 0.0.0.0` 启动；电脑与手机连接同一 Wi-Fi，手机打开 `http://电脑的局域网IPv4:8000`。Windows 防火墙仅为该 Python 放行专用网络入站。这个 HTTP 地址用于本机和可信局域网，公网部署使用下面的 HTTPS 入口。使用自定义端口或监听地址时，更新也传入相同的 `-Port` / `-BindAddress`。

### 公网服务器（Linux + systemd + Caddy）

目前先交付本地体验版，公网服务器和域名待提供。建议用国内可直连的 Ubuntu 24.04 云服务器，项目与本地使用同一个 Python 部署入口。

1. 安装 Python、venv、pip、Git、Caddy，创建独立用户和目录。以下按 Ubuntu 24.04 执行：

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-venv python3-pip git caddy
   sudo useradd --system --create-home --shell /bin/bash kanshan
   sudo install -d -o kanshan -g kanshan /opt/kanshan-mystery
   sudo -u kanshan git clone https://github.com/sleepz710/kanshan-mystery.git /opt/kanshan-mystery
   cd /opt/kanshan-mystery
   sudo -u kanshan python3 -m venv .venv
   sudo -u kanshan .venv/bin/python -m pip install -r requirements.txt
   sudo -u kanshan cp .env.example .env
   sudo chmod 600 .env
   sudo -u kanshan nano .env
   ```

2. 在 `.env` 追加与本地相同的 `DEPLOY_USERNAME` / `DEPLOY_PASSWORD`。先用 `LLM_MOCK=1` 验证；真实模型按上表填写共用密钥、演员和编剧配置，将 `LLM_MOCK` 改为 `0`。key 只写在服务器 `.env`，不提交、不写进 Caddyfile。已有服务器更新时对照 `.env.example` 补齐变量，保留原有配置。

3. 安装服务。只运行一个 worker，游戏和生成任务保存在该进程内。

   ```bash
   sudo cp deploy/kanshan.service /etc/systemd/system/kanshan.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now kanshan
   sudo -u kanshan .venv/bin/python deploy/smoke.py --wait
   ```

4. 域名 A 记录指向服务器。首次独立部署时，把模板安装为 `/etc/caddy/Caddyfile`，在该文件中将示例域名改成实际域名；保留仓库模板不变，让更新时的工作区保持干净。服务器安全组和防火墙放行 TCP 80、443，8000 仅监听本机。Caddy 自动签发和续期 HTTPS 证书。服务器已有网站时，将本站点块追加到现有配置，跳过下面安装模板的命令。

   ```bash
   sudo install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
   sudo nano /etc/caddy/Caddyfile
   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo systemctl reload caddy
   sudo -u kanshan .venv/bin/python deploy/smoke.py --base-url https://实际域名
   ```

5. 更新命令（以有 sudo 权限的管理员执行；拉代码、安装依赖和测试仍使用 `kanshan` 用户）：

   ```bash
   cd /opt/kanshan-mystery && sudo bash deploy/update.sh
   ```

   脚本拉取当前分支的上游、安装依赖、运行 pytest，通过后重启并验证口令和开局。服务日志：`sudo journalctl -u kanshan -n 100 --no-pager`。修改 `.env` 后执行 `sudo systemctl restart kanshan`。

### 验收与已知问题

- 电脑、手机都要检查：输入口令、打开首页、招牌案件开局、对话、生成剧场生成并开局；公网地址还要用手机流量验证。`smoke.py` 自动检查口令、首页、API 文档、案件列表和第二版开局结构，不调用模型。
- 当前已接入第二版后端和四角色招牌案件，游戏前端和生成剧场路由尚未合入；现在可以通过 `/docs` 联调，完整网页体验等对应任务合入后验收。
- 重启会清空进行中的对局、编剧对话和生成任务；更新前通知试玩人员。`data/stories/` 留在服务器磁盘，更新不删除生成剧本。
