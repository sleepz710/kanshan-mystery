# SPEC:看山谜案馆

2026-11-02 · 三天版本。完整的多智能体设计见 `docs/g-mystery-draft.md`,这里只保留三天内做得完的部分。

## 1. 一句话介绍

多智能体反诈推理游戏:玩家当调查员,和几个各有记忆、各知一部分真相的 AI 角色对话、出示证据,查清一桩刷单返利诈骗,破案后学到反诈知识。主题:AI 陪伴交互(叙事类 AI 应用)。

## 2. 用户与场景

大学生。反诈宣传常见的是讲座和海报;这里换成一局十分钟的推理游戏,玩家自己把骗局一步步拼出来,更记得住。

## 3. 演示主流程

视频按这个流程录,具体情节以剧本为准。

1. 进入游戏,看案情:新生小林被骗走两万元学费。
2. 问小林,拿到兼职群截图和转账回单;回单上的收款卡属于隔壁宿舍的周同学。
3. 把转账回单出示给周同学,他先否认,信任度上来后承认卖过银行卡。
4. 把阿凯拉人进群的证据出示给小林,小林去找阿凯对质;事件流显示两人争吵,解锁新线索。
5. 卡住时,导演给出提示。
6. 提交推理:诈骗类型、赃款经过谁的卡、谁把小林拉进群、关键证据。
7. 结局页:得分、真相复盘、三条反诈知识点。

## 4. 范围

### 必做

- 一个剧本:3 个角色(小林、阿凯、周同学),7 条左右线索,10 分钟内能玩完。
- 世界引擎:读剧本 YAML,管理已获线索、每个角色的信任度、解锁条件、事件记录。
- 角色智能体:按知情范围和信任度决定说什么、交出哪些线索,记得和玩家聊过什么。
- 角色对质:剧本里的触发条件满足时,两个角色智能体对话一轮,结果显示在事件流。
- 核查:每条角色回复显示前,检查有没有说出这个角色不能说的事实,越界就重写一次。
- 导演:用规则实现,连续若干回合没有新线索就给提示。
- 结局:选择题由程序判分,复盘和反诈知识点取自剧本。
- 网页界面:角色列表、对话区、线索板、出示证据、事件流、提交推理、结局页。
- 模拟模式:不调用模型、返回固定回复,前端没有 API key 也能开发。

### 加分(第三天有余力再做)

- 泄密率测试:对每个角色提几十个刺探问题,统计核查开、关两种情况的泄密率,放进视频。
- 导演以刘看山的身份出场,当玩家的搭档(比赛例题里就有「刘看山 AI 数字伙伴」;形象用比赛方提供的素材)。
- 部署到公网,填作品体验链接。

### 不做

多个剧本、存档读档、账号系统、语音。

## 5. 模块划分

| 模块 | 文件 | 职责 | 任务 |
|---|---|---|---|
| 剧本 | `stories/lost-tuition.yaml` | 事实、角色、线索、事件、提示、结局题 | 01 |
| 世界引擎 | `backend/engine.py` | 加载剧本、游戏状态、解锁规则、判分 | 02 |
| 接口 | `backend/app.py` | FastAPI 路由,同时提供前端静态文件 | 02 |
| 模型调用 | `backend/llm.py` | OpenAI 兼容客户端,读 `.env`;模拟模式 | 02 |
| 智能体 | `backend/agents.py` | 角色回复、核查、角色对质 | 03 |
| 前端 | `frontend/` | 游戏界面 | 04 |
| 评测 | `eval/leak_test.py` | 泄密率统计(加分) | 06 |

## 6. 接口与数据格式

### 6.1 剧本 YAML

```yaml
id: lost-tuition
title: 一笔消失的学费
intro: 开场案情,玩家可见
facts:                              # 只有引擎和智能体能看到
  - id: f1
    text: 阿凯把兼职群推给了小林
characters:
  - id: xiaolin
    name: 小林
    avatar: xiaolin.png
    profile: 大一新生,被骗走两万元学费   # 玩家可见
    persona: 性格和说话方式              # 给模型看
    knows: [f1, f2, f3]                  # 知情范围
    secrets:                             # 条件满足前不会说
      - fact: f2
        until: {trust: 2}
    trust_start: 0
clues:
  - id: c1
    title: 兼职群邀请截图
    content: 线索卡上显示的内容
    holder: xiaolin                      # 由谁交出
    requires: {trust: 1}                 # 交出条件,可省略
events:
  - id: e1
    when: {shown: c5, to: xiaolin}       # 把 c5 出示给小林时触发
    confront: [xiaolin, akai]            # 两个角色对质一轮
    unlock: [c6]
hints:
  - text: 也许该问问阿凯,他是怎么知道这个兼职群的
ending:
  questions:
    - id: q1
      text: 小林遇到的是哪种诈骗?
      options: [刷单返利, 冒充客服退款, 网络贷款]
      answer: 刷单返利
  truth: 真相复盘全文
  lessons: [反诈知识点一, 反诈知识点二, 反诈知识点三]
```

条件只有两种写法:`{trust: n}` 表示这个角色对玩家的信任度不低于 n;`{shown: 线索id}` 表示玩家给这个角色看过这条线索。事件的 `when` 另写 `to`,指出示给哪个角色。

### 6.2 前后端接口

| 方法 | 路径 | 请求 | 返回 |
|---|---|---|---|
| POST | `/api/games` | `{"story_id": "lost-tuition"}` | `{game_id, title, intro, characters: [{id, name, avatar, profile}], questions: [{id, text, options}]}` |
| POST | `/api/games/{game_id}/talk` | `{"character_id": "xiaolin", "text": "……"}` | 回合结果 |
| POST | `/api/games/{game_id}/show` | `{"character_id": "zhou", "clue_id": "c4"}` | 回合结果 |
| POST | `/api/games/{game_id}/accuse` | `{"answers": {"q1": "刷单返利"}}` | `{score, total, results: {q1: true}, truth, lessons}` |

回合结果:

```json
{
  "reply": "角色说的话",
  "new_clues": [{"id": "c1", "title": "兼职群邀请截图", "content": "……"}],
  "events": [{
    "type": "confront",
    "text": "你听到走廊里小林和阿凯吵了起来",
    "lines": [{"speaker": "xiaolin", "text": "……"}, {"speaker": "akai", "text": "……"}]
  }],
  "hint": null,
  "trust": {"xiaolin": 2}
}
```

### 6.3 角色智能体的输出

模型以 JSON 返回:

```json
{"reply": "角色说的话", "reveal": ["c1"], "trust_delta": 1}
```

引擎只接受当前满足交出条件的线索,其余忽略;`trust_delta` 只取 -1、0、1。

### 6.4 核查的输出

```json
{"ok": false, "leaked": ["f2"]}
```

`ok` 为 false 时,带着越界的事实提醒角色重写一次。

## 7. 技术栈

- 后端:Python 3.11+、FastAPI、uvicorn、PyYAML、openai SDK。
- 模型:任一 OpenAI 兼容 API(DeepSeek、通义千问等)。`.env` 里配 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`;`LLM_MOCK=1` 开模拟模式。
- 前端:原生 HTML/CSS/JS,由 FastAPI 直接提供,不需要构建工具。
- 运行:`pip install -r requirements.txt`,`uvicorn backend.app:app --reload`,打开 http://localhost:8000。
- 部署:可选,本地跑通就能录视频。

## 8. 正确性评测

- 引擎:单元测试覆盖解锁条件、事件触发、判分。
- 泄密率:见第 4 节加分项。
- 试玩:组内每人完整玩一局,记录卡住的地方和角色说错的话。

## 9. 评分对照

| 评分项 | 我们靠什么拿分 |
|---|---|
| 技术实现 40% | 多智能体:角色各有知情范围和记忆,角色之间会对质,核查拦下越界回答;事实由引擎保管,流程稳定;有单元测试和泄密率数据 |
| 创意与价值 30% | 把反诈教育做成可玩的推理游戏,覆盖刷单返利和出售银行卡两类学生常见风险 |
| 用户体验 30% | 线索板、出示证据、事件流;一局十分钟;界面风格统一 |

## 10. 提交物

| 提交项 | 做法 |
|---|---|
| 作品基本信息(文本) | 第三天写,素材取自本文件 |
| 作品海报(图片) | 第三天做 |
| 项目源码 | GitHub 仓库,README 写清怎么运行 |
| 演示视频 | 按第 3 节流程录,传 B 站 |
| 作品体验链接 | 可选 |
