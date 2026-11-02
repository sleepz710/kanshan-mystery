# My_agent

比赛「高级组」参赛项目:做一个 AI 智能体,主题在前四个可选主题里选一个,目前处于选题阶段。项目名定下来后替换这个标题。

进度和待办见 [docs/STATUS.md](docs/STATUS.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `AGENTS.md` | 所有 AI 编程助手共用的规则(Codex 等工具会自动读取) |
| `CLAUDE.md` | 让 Claude Code 读取 AGENTS.md |
| `SPEC.md` | 产品与技术规格,选题后填写 |
| `TASKS.md` | 任务清单、认领和交接 |
| `docs/STATUS.md` | 项目进度、已定和待定事项 |
| `docs/assignment.md` | 比赛主题与评分标准 |
| `docs/ideas.md` | 选题头脑风暴 |
| `docs/assets/` | 图片等素材 |

## 怎么一起干活

1. `git pull` 拿到最新的 `main`。
2. 在 `TASKS.md` 认领任务,建分支 `task/<编号>-<英文短名>`。
3. 让你的 AI 助手开工前先读 `AGENTS.md`。不会自动读取它的工具,在对话第一句让它去读。
4. 做完提 Pull Request;收工前在 `TASKS.md` 写交接。

## 推送到 GitHub

在 GitHub 新建一个空仓库(不勾选添加 README),然后在本目录运行:

```
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main
```
