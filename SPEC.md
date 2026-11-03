# SPEC:看山谜案馆

2026-11-02 · 第二版。11 月 4 日(周三)晚提交,最迟 11 月 5 日(周四)。招牌案件的完整故事见 `docs/story-v2.md`。

## 1. 一句话介绍

AI 推理剧场:玩家和几个各怀秘密的 AI 角色对话、出示证据、拆穿谎话,查出真相。案子有两种来源:团队打磨的招牌案件,和编剧智能体根据玩家输入当场改编的新案子。玩法参考海龟汤:开局一段有矛盾的汤面,玩家查出汤底。主题:AI 陪伴交互,对应例题「刘看山 AI 数字伙伴」「叙事类 AI 应用」。

## 2. 用户与场景

喜欢推理、剧本杀、海龟汤的年轻人。招牌案件一局约二十分钟。玩完了,把一碗海龟汤、一段小说、一个网址,或者一句「我想玩一个发生在……的案子」发给编剧,一两分钟后开一局新的。

## 3. 演示流程

视频按这个流程录。

1. 首页:案件列表和「新建剧场」入口。
2. 打开招牌案件「一笔消失的学费」,看汤面,刘看山打招呼。
3. 问话、出示证据:楼层群截图拆穿周明;卖卡聊天记录和收款记录两次拆穿陈默;小林和阿凯在走廊对质。
4. 问刘看山一个是非题;卡住时收到他的提示。
5. 提交推理,进入「真相大白」结局,看评级、汤底和反诈知识点。
6. 回到首页,在「新建剧场」里贴一碗海龟汤,和编剧聊两句,生成新案子,开局玩几步。
7. 打开「出题给朋友」再生成一个案子,把分享链接发给队友,在出题人页面看他卡在哪。

## 4. 范围

### 必做

- 招牌案件:4 个角色、12 条线索、5 句谎话、1 个对质事件、5 道结局题、3 个结局。
- 世界引擎:读剧本 YAML,管理线索、信任度、谎话、事件、提示、结局,规则见 6.5。
- 角色智能体:按知情范围、谎话和信任度回答,决定交出哪些线索,记得和玩家聊过什么。
- 核查:每条角色回复显示前检查越界和矛盾,不通过重写一次。
- 对质:事件触发时,两个角色智能体对话一轮。
- 刘看山:汤主问答,一局 5 次;按剧本分阶段给提示。
- 结局:按答案进入不同结局并给评级;坏结局可以重新调查,也可以直接揭晓汤底。
- 生成剧场:像和 LLM 聊天一样,玩家输入文字、上传文本文件或贴网址,编剧智能体改编出新剧本,检查通过后进入案件列表。
- 剧本检查器:程序检查加可解性检查;不通过就带着问题清单回编剧重写。
- 网页界面:首页案件列表、生成剧场的对话页、游戏页、结局页。
- 模拟模式:不调模型,返回固定内容,前端没有 key 也能开发。
- 评测:泄密率;AI 完整试玩,统计生成剧本的破案率。数据放进视频和答辩。
- 部署:部署到公网,提交作品体验链接,评委可以直接玩。
- 出题给朋友:生成的案子有分享链接,朋友打开就能玩;出题人能看到完整剧本和朋友卡在哪。

### 不做

账号系统、存档读档、多人同时玩一局。

## 5. 模块划分

| 模块 | 文件 | 职责 | 任务 |
|---|---|---|---|
| 招牌案件 | `stories/lost-tuition.yaml` | 第一个完整剧本,也是格式范例 | 01 |
| 世界引擎 | `backend/engine.py` | 加载剧本、游戏状态、条件判定、拆穿、保底、提示、结局、评级 | 02 |
| 接口 | `backend/app.py` | FastAPI 路由,同时提供前端静态文件 | 02 |
| 模型调用 | `backend/llm.py` | 演员、编剧两组模型的客户端;模拟模式 | 02 |
| 角色、核查、对质 | `backend/agents.py` | 角色回复、核查、对质 | 03 |
| 刘看山 | `backend/kanshan.py` | 汤主问答 | 05 |
| 编剧 | `backend/studio/` | 生成剧场的对话、读文件、抓网页、改编、审稿、生成任务 | 06 |
| 剧本检查 | `backend/studio/check.py` | 程序检查、可解性检查 | 07 |
| 游戏前端 | `frontend/` | 首页、游戏页、结局页 | 04 |
| 生成剧场前端 | `frontend/studio/` | 对话页、上传、进度 | 08 |
| 评测 | `eval/` | 泄密率、AI 完整试玩 | 10 |
| 部署 | `deploy/` | 服务器配置、启动和更新脚本 | 12 |
| 出题给朋友 | `backend/studio/share.py`、`frontend/share/` | 分享链接、出题人页面 | 13 |

生成的剧本存到 `data/stories/`,不入库。

## 6. 接口与数据格式

### 6.1 剧本 YAML

招牌案件和编剧生成的剧本都用这个格式。

```yaml
id: lost-tuition
title: 一笔消失的学费
source: official                     # official 招牌案件 | generated 生成
intro: 汤面,玩家开局看到的
facts:                               # 只有引擎和智能体能看到
  - id: f1
    text: 陈默用小号「鹿鸣兼职」在楼层群收银行卡
characters:
  - id: chenmo
    name: 陈默
    avatar: chenmo.png
    profile: 大三学长,兼职群群主       # 玩家可见
    persona: 性格、说话方式、动机       # 给模型看
    knows: [f1, f2, f3]               # 知情范围
    secrets:                          # 条件满足前不说
      - fact: f2
        until: {trust: 2}
    lies:                             # 拆穿前坚持的谎话
      - id: l4
        claim: 收卡、刷单我都不清楚,周明我也不太熟
        until: {shown: c7}            # 拆穿条件
        admit: f3                     # 拆穿后承认的事实
      - id: l5
        claim: 那天是网友托我取个快递,我不知道里面是卡
        until: {exposed: l4, shown: c9}
        admit: f1
    trust_start: 0
clues:
  - id: c9
    title: 周明的收款记录
    content: 线索卡上显示的内容
    holder: zhouming                  # 由谁交出
    requires: {exposed: l3}           # 交出条件,可省略
events:
  - id: e1
    when: {shown: c3, to: xiaolin}    # 把 c3 出示给小林时触发
    confront: [xiaolin, akai]         # 两个角色对质一轮
    unlock: [c5]                      # 对质后玩家直接拿到的线索
kanshan:
  greeting: 刘看山的开场白
  hints:                              # 按阶段排,见 6.5
    - done: {exposed: l3}
      vague: 周明说卡丢了。有人能证明他在撒谎吗?
      direct: 把楼层群截图出示给周明。
ending:
  questions:
    - id: q1
      text: 两万元为什么会进周明名下的卡?
      options:
        - 周明把卡卖了,卡在骗子手里收钱
        - 周明就是骗子
        - 小林转错了账户
      answer: 周明把卡卖了,卡在骗子手里收钱
  endings:                            # 从上往下匹配,第一个满足的生效
    - id: truth
      title: 真相大白
      when: {correct: [q2, q5]}       # 这几题都答对
      text: 结局正文
    - id: wronged
      title: 冤枉好人
      when: {chose: {q1: 周明就是骗子}}  # 选了这个选项
      text: 结局正文
      retry: true                     # 提供「重新调查」
    - id: half
      title: 只查到一半
      text: 结局正文                     # 不写 when,兜底
      retry: true
  truth: 汤底全文
  lessons: [知识点一, 知识点二, 知识点三]  # 可省略
```

条件写法:

| 写法 | 含义 |
|---|---|
| `{trust: n}` | 这个角色对玩家的信任度不低于 n |
| `{shown: c3}` | 玩家给这个角色看过 c3 |
| `{has: c3}` | 玩家已经拿到 c3 |
| `{exposed: l4}` | 谎话 l4 已被拆穿 |
| `{event: e1}` | 事件 e1 已发生 |

「这个角色」指条件所属的角色:`secrets`、`lies` 属于所在角色,线索的 `requires` 属于 `holder`。一个条件里写多项时,全部满足才算。事件的 `when` 另写 `to`,指出示给哪个角色。

YAML 的 `[a, b]` 写法里,逗号会把文字拆开;含逗号的选项用 `- ` 一行一个。

### 6.2 前后端接口

游戏:

| 方法 | 路径 | 请求 | 返回 |
|---|---|---|---|
| GET | `/api/stories` | | `[{id, title, intro, source, characters}]`,`characters` 是人数 |
| POST | `/api/games` | `{"story_id": "lost-tuition"}` | `{game_id, title, intro, characters: [{id, name, avatar, profile}], questions: [{id, text, options}], kanshan: {greeting, asks_left}}` |
| POST | `/api/games/{game_id}/talk` | `{"character_id": "xiaolin", "text": "……"}` | 回合结果 |
| POST | `/api/games/{game_id}/show` | `{"character_id": "zhouming", "clue_id": "c4"}` | 回合结果 |
| POST | `/api/games/{game_id}/ask` | `{"question": "周明是骗子吗"}` | `{"answer": "不是", "asks_left": 4}`;次数用完返回 409 |
| POST | `/api/games/{game_id}/accuse` | `{"answers": {"q1": "……"}}` | `{score, total, results: {q1: true}, ending: {id, title, text, retry}, rating}` |
| POST | `/api/games/{game_id}/reveal` | | `{truth, lessons}` |

回合结果:

```json
{
  "reply": "角色说的话",
  "new_clues": [{"id": "c4", "title": "楼层群截图", "content": "……"}],
  "events": [
    {"type": "exposed", "character": "zhouming", "lie": "l3", "text": "周明的说法被拆穿了"},
    {"type": "confront", "text": "你听到走廊里小林和阿凯吵了起来",
     "lines": [{"speaker": "xiaolin", "text": "……"}, {"speaker": "akai", "text": "……"}]}
  ],
  "hint": null,
  "trust": {"zhouming": 1}
}
```

`hint` 有值时是刘看山说的提示。`accuse` 之后,结局带 `retry: true` 的可以继续问话、再次提交,保留已获线索、信任度和使用次数。`rating` 为字符串(S/A/B/C)。`reveal` 需要先提交过一次推理,返回汤底后结束本局。汤主问答只有成功返回合法答案才扣次数。

生成剧场:

| 方法 | 路径 | 请求 | 返回 |
|---|---|---|---|
| POST | `/api/studio/chats` | `{"mode": "play"}`,`mode` 为 play 自己玩 / share 出题给朋友 | `{chat_id, reply}`,`reply` 是编剧的开场白 |
| POST | `/api/studio/chats/{chat_id}/messages` | multipart:`text`,可带多个 `files` | `{reply, job}`;开始生成时 `job` 为 `{id}`,否则为 null |
| GET | `/api/studio/jobs/{job_id}` | | `{status, progress, story_id, owner_token, error}`;`status` 为 running / done / failed;`owner_token` 只在 share 模式给 |
| GET | `/api/stories/{story_id}/owner` | 请求头 `X-Owner-Token` | `{story, games: [{game_id, turns, clues, exposed, ending}]}`:完整剧本和朋友们的对局进度 |

`progress` 只写不剧透的话,例如「编剧正在布置现场」。`done` 时 `story_id` 可以直接用来开局。分享链接是 `/?story=<story_id>`,首页带这个参数时直接开局。

### 6.3 角色智能体

模型以 JSON 返回:

```json
{"reply": "角色说的话", "reveal": ["c1"], "trust_delta": 1}
```

提示词里只放这个角色的人设、知情范围(去掉还没解锁的秘密)、还没拆穿的谎话、已拆穿谎话要承认的事实、信任度、和玩家的对话记录、现在能交出的线索。拆穿前坚持谎话,拆穿后承认。引擎只接受当前满足交出条件的线索;`trust_delta` 只取 -1、0、1。

### 6.4 核查

模型以 JSON 返回:

```json
{"ok": false, "leaked": ["f2"], "contradiction": "谎话被拆穿后,还在说卡丢了"}
```

越界:说出知情范围外、或还没解锁的事实。拆穿前说谎话原文不算越界;拆穿后还坚持,算矛盾。`ok` 为 false 时,带着问题让角色重写一次。

### 6.5 引擎规则

一个回合(`talk` 或 `show`)按这个顺序走:

1. `show` 时先判定:`until` 已满足的谎话标记为拆穿,产生 `exposed` 事件;`when` 已满足的事件触发。
2. 调角色智能体,然后核查。
3. 收下 `reveal` 里合法的线索,按 `trust_delta` 改信任度。
4. 对质事件调对质,`unlock` 的线索交给玩家;对质后满足条件的谎话也标记为拆穿。
5. 保底:谎话被拆穿,该角色信任度 +1;和一个角色累计聊满 4 回合,信任度至少为 1。信任度上限 3。
6. 提示:连续 3 回合没有新线索,刘看山找 `hints` 里第一个 `done` 还没满足的阶段,先给 `vague`;同一阶段再卡 3 回合,给 `direct`。

结局:`accuse` 按 6.2 判分,再按 `endings` 从上往下匹配。`when` 有两种写法:`{correct: [题号]}` 表示这些题都答对,`{chose: {题号: 选项}}` 表示选了这个选项;不写 `when` 的是兜底结局。

评级由引擎返回字符串:全对、成功调查回合不超过 20、汤主问答不超过 2 次为 S;其余答对至少 80% 为 A、至少 60% 为 B、否则 C。调查回合只计算成功的 `talk` 和 `show`;失败请求不计数,问答单独计数,重新调查保留这些计数。前端按这个字段显示评级。

### 6.6 刘看山

- 汤主问答:模型读剧本的全部事实和汤底,对玩家的问题只答「是」「不是」「不重要」之一,以 JSON `{"answer": "是"}` 返回。问题不能用是非回答时,答「不重要」。一局 5 次。
- 提示由引擎按 6.5 触发,文字取自剧本的 `kanshan.hints`。
- 形象:比赛方没给素材,头像用我们自己的「看山」徽标,不自己画北极熊。

### 6.7 生成剧场

编剧智能体和玩家像聊天一样对话,用编剧模型,带三个工具:

| 工具 | 作用 |
|---|---|
| `read_file` | 读玩家上传的文本文件(txt、md) |
| `fetch_url` | 抓网页正文;一页有好几碗汤时让玩家挑一碗;抓不到就请玩家粘贴文字 |
| `generate_story` | 带着素材和改编策略启动生成任务 |

对话规则:

- 两种模式,建对话时选:`play` 自己玩,对话里不剧透,不说出生成剧本的真相和人物的秘密;`share` 出题给朋友,编剧可以和出题人讨论剧情,生成后给出完整剧本、分享链接和 `owner_token`,`owner_token` 存在出题人的浏览器里。
- `play` 模式开始生成前最多问一个问题,默认值按素材预选:素材里有汤底,默认「看过答案」;只有汤面,默认「没看过」;只有想法,默认「全新」。玩家说「直接开始」就用默认值。
- 题材全接。变格(超自然、科幻)素材改成现实逻辑的版本。只做改编,不照搬原文。

改编策略:

| 策略 | 编剧怎么做 |
|---|---|
| 没看过答案 | 保留原汤底的核心反转,扩成有人物、有证据、有谎话的剧场世界 |
| 看过答案 | 汤面保留,汤底重写;原汤底做成诱饵,前期证据指向它,查到一半被推翻 |
| 全新 | 只借题材和氛围,写一个全新的案子 |

生成任务:

1. 读懂素材,定下真相和时间线。
2. 安排 3 到 4 个人物:谁在场、各知道哪部分、谁有理由隐瞒。
3. 把关键事实落成 8 到 12 条线索,写好拿到条件;安排 2 到 5 句谎话和拆穿它们的证据。
4. 写汤面、刘看山的开场白和提示、3 到 5 道结局题、2 到 3 个结局、汤底。
5. 审稿:用编剧模型通读找漏洞,改一遍。
6. 剧本检查(6.8),不通过就带着问题清单回到第 3 步,最多 3 轮。3 轮后仍不通过,照样保存并记 `checked: false`,编剧在对话里说清哪里有问题,由玩家决定玩不玩。
7. 写入 `data/stories/<id>.yaml`,`source: generated`,出现在案件列表。

### 6.8 剧本检查

`check(story) -> {"ok": bool, "problems": ["……"]}`。`problems` 每条一句,写清哪里坏了,例如「c7 拿不到:它要求 l3 被拆穿,但拆穿 l3 的 c4 拿不到」。

- 程序检查:格式和字段齐全;编号引用都存在;从开局状态出发按条件推演,所有线索都拿得到、所有谎话都拆得穿、每个结局都可能触发;每道结局题的答案在选项里;`admit`、`secrets` 的事实在该角色的 `knows` 里。信任度条件按保底规则视为最终能满足。
- 可解性检查:两次模型调用。只给汤面,用编剧模型答结局题,答对超过一半说明太容易;给出全部线索,用演员模型答,有题答错说明推不出来。两种情况都算不通过。

### 6.9 生成剧场后端交接（任务 07 → 06 → 13）

- 检查器是异步 `await check(story)`；`check_structure(story)` 只做程序检查。模拟模式返回固定盲答，不表示已经完成真实语义评测。
- 06 补充 `requirements.txt` 的 `python-multipart`、`trafilatura` 依赖，在 `create_app` 的静态目录挂载前调用 `mount_studio(application)`；应用通过 `app.state.studio` 持有会话和生成任务。测试放 `backend/studio/test_studio.py`；既有 API 路由清单断言改为包含游戏接口，允许新增剧场路由。`.env.example` 补编剧/演员配置并保留旧版 `LLM_MODEL`，方便 02 升级前联调。
- 生成剧本使用服务端随机 `generated-<uuid>` 编号，写入 `data/stories/`；最多三轮“生成、审稿、检查”。仍不通过但格式完整时存 `checked: false`，只返回编号和不剧透的问题提示，由玩家决定开局；格式已损坏的模型输出返回失败，不发布不能读取的 YAML。
- 自己玩时公开回复采用固定的流程文案，模型的剧情讨论只在 share 模式显示；详细检查问题保存在服务端，play 模式不回传涉及真相的编号或原文。
- 聊天、任务、游戏进度目前保存在单服务进程内，重启清空；生成 YAML 和出题人令牌摘要落盘。关闭服务时取消未完成的生成任务，重新打开对话可重试。
- 02 已按 6.2 从 `stories/` 与 `data/stories/` 加载及列举剧本；挂载剧场时复用引擎的 `generated_stories_dir`，自定义路径也保持一致。13 从 `app.state.engine.games` 读取匹配 `state.story.id` 的对局；进度字段以 `turns`、`acquired_clues`、`exposed`、`ending` 为约定，旧引擎回合数从 histories 计算，未接入的拆穿与结局显示为空。
- 分享模式的 owner 接口必须验证 `X-Owner-Token`，令牌只在对应生成任务返回，磁盘只存 SHA-256 摘要。分享链接为 `/?story=<story_id>`，share 任务完成时额外返回 `share_url`；完整剧本仅从 owner 接口返回，进度接口与案件列表都不含剧本真相。13 在 `studio/service.py` 的原子发布阶段接入 `share.py`，在剧场路由挂载处注册 owner 路由；本轮只实现 13 的后端，页面由前端任务对接。

## 7. 技术栈

- 后端:Python 3.11+、FastAPI、uvicorn、PyYAML、openai SDK、python-multipart(上传文件)、trafilatura(网页正文)。
- 前端:原生 HTML/CSS/JS,由 FastAPI 直接提供,不需要构建工具。
- 模型:DeepSeek 官方 API(OpenAI 兼容),也支持 OpenAI。分两组:

| 用途 | 默认模型 | 思考模式 |
|---|---|---|
| 演员:角色、核查、对质、刘看山、AI 试玩、可解性检查里的「给全部线索」 | `deepseek-flash` | 关,要快 |
| 编剧:编剧对话、生成、审稿、可解性检查里的「只给汤面」 | `deepseek-flash` | 开 |

- `.env`:

  ```
  LLM_BASE_URL=https://api.deepseek.com
  LLM_API_KEY=
  LLM_ACTOR_MODEL=deepseek-flash
  LLM_WRITER_MODEL=deepseek-flash
  # 编剧换成 OpenAI 时填这两项,留空就用上面的
  LLM_WRITER_BASE_URL=
  LLM_WRITER_API_KEY=
  LLM_MOCK=0
  ```

- DeepSeek 默认开思考模式。演员的请求要加 `extra_body={"thinking": {"type": "disabled"}}`;思考模式下 `temperature` 不生效。OpenAI 不认这个参数,`llm.py` 按接口地址决定加不加。细节以 [DeepSeek 文档](https://api-docs.deepseek.com/guides/thinking_mode/) 为准。旧模型名 `deepseek-chat`、`deepseek-reasoner` 按官方公告 2026-07-24 下线,不要再用。
- DeepSeek 演员请求使用 `temperature=0`,优先保证事实与结构稳定;编剧思考模式和其他服务不附加这个参数。
- 运行:`pip install -r requirements.txt`,`uvicorn backend.app:app --reload`,打开 http://localhost:8000。
- 部署:部署到公网,提交体验链接,平台见 `docs/STATUS.md`。服务器上的 key 只放环境变量;体验版加访问口令,或按 IP 限制每天开局和生成的次数,防止 key 被刷。部署和更新步骤写进 README。

## 8. 正确性评测

- 引擎:单元测试覆盖各种条件、拆穿、保底、提示阶段、结局匹配。
- 剧本检查器:招牌案件能通过;故意弄断一条线索的拿到途径、让一道结局题没有线索支撑,都能查出来。
- 泄密率:对每个角色提几十个刺探问题,统计核查开、关两种情况的泄密率。
- AI 完整试玩:玩家智能体玩生成的剧本,统计破案率和平均回合数。
- 试玩:组内每人完整玩一局招牌案件,再生成并玩一局新案子,记录卡住的地方、角色说错的话和生成剧本的漏洞。

## 9. 评分对照

| 评分项 | 我们靠什么拿分 |
|---|---|
| 技术实现 40% | 多智能体:角色各有知情范围、记忆和谎话,被证据逼着改口;对质;核查;刘看山当汤主;编剧、审稿、检查组成生成流水线。事实由引擎保管。单元测试、剧本检查器,加上泄密率和破案率数据 |
| 创意与价值 30% | 海龟汤加证据推理加 AI 角色;任何素材都能变成一局推理;招牌案件取材于校园收卡和刷单诈骗 |
| 用户体验 30% | 像聊天一样生成剧场;拆穿谎话的效果;线索板、事件流;多结局和评级 |

## 10. 提交物

11 月 4 日晚提交。

| 提交项 | 做法 |
|---|---|
| 作品基本信息(文本) | 素材取自本文件 |
| 作品海报(图片) | 11 月 4 日下午做 |
| 项目源码 | GitHub 仓库,README 写清怎么运行、怎么配 `.env` |
| 演示视频 | 按第 3 节流程录,传 B 站 |
| 作品体验链接 | 部署后的网址 |
