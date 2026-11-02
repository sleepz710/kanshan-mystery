# 看山谜案馆

多智能体反诈推理游戏:玩家当调查员,和几个各有记忆、各知一部分真相的 AI 角色对话、出示证据,查清一桩刷单返利诈骗。比赛「高级组」参赛作品,主题 AI 陪伴交互,开发中。

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
| `docs/g-mystery-draft.md` | 多智能体设计草案 |
| `docs/assets/` | 图片等素材 |

## 怎么一起干活

1. 第一次:`git clone https://github.com/sleepz710/kanshan-mystery.git`。
2. 任务当面分好。在仓库目录里打开自己的 AI 助手(Codex、Claude Code),第一句说「做 TASKS.md 里的任务 02,按 AGENTS.md 的流程来」。不会自动读取 `AGENTS.md` 的工具,先让它去读。
3. agent 在任务分支上开发,做完自己开 Pull Request;在 GitHub 上看过改动后点合并。
