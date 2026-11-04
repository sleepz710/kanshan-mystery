# 任务20角色修复后的桌面v2验收

## 分支与构建源码

PR #41、#43已由用户合并，本轮从main `aee60ba`新建 `task/20-role-package`。任务18完整来源为 `77e449e`，桌面素材生命周期修复为 `75279d7`，素材判意用途修复为 `2a8a463`。最终包从 `2a8a463144ce62d2ffd18bb67418ec7f99ccea1c` 构建，完整源码tree为 `0fbb64f3dc29b1272c2cb2ca9c337375531aec2a`。用户已合并PR #42，最新main为 `16a13da`。本任务同步其来源后发布独立PR。

同模型仍为 `gpt-5.4-2026-03-05`，演员关闭思考，剧情设计高思考。自己玩素材判意与策略选择保留编剧模型、接口及密钥配置，按本轮真实固定案例结果关闭思考。出题讨论、自然语言设计和开局盲答沿用编剧高思考用途。OpenAI快速1200秒、精修1800秒，单次540秒。DeepSeek快速600秒、精修900秒。耗时逐项保留。

## 定位与修复

素材对话已分配提供方ID，窗口正常退出0之后，远端任务仍继续运行。调用点缺少服务生命周期登记，ASGI取消与事件循环退出打断了远端有界清理。实际uvicorn/ASGI/事件循环的零付费重现，在原码中exit0前未开始取消；修复后exit0前 `cancel_done=true`。

素材模型任务登记到已有服务任务集合，HTTP取消显式取消其任务，服务close等待已有gather完成有界清理。普通成功任务会从集合移除。三项回归覆盖成功移除、取消等待、无半写对话状态。证据见 [asgi-before.json](task20-role-v2/asgi-before.json)、[asgi-after.json](task20-role-v2/asgi-after.json) 与 [material-observer-diagnostic.json](task20-role-v2/material-observer-diagnostic.json)。

修复退出后的一次真实素材对话达到生产540秒期限，远端同ID取消200，生成job为0，后续付费已停止。记录见 [final-material-timeout.json](task20-role-v2/final-material-timeout.json)。此前观察器180秒提前结束与生产清理缺口分列保留，现观察等待覆盖单次540秒、精修整体1800秒及保存余量，进程允许90秒正常退出。

素材决策新增可选 `intent` 用途，只有自己玩判意传入true。OpenAI使用同编剧配置的Responses none，DeepSeek在同编剧配置关闭思考。play回复要求空字符串，程序生成固定确认文字，原始模型草稿受公开回复与设计材料隔离。默认调用与share讨论保留原行为。

## 素材真实校准

原五个局部none实验，按现有产品契约的判意、策略和素材保留各5/5，原硬性generate预期2/5。两份raw回复存在额外风格邀请和擅自4人10线索草稿，公开固定回复与设计材料隔离检查通过。原记录及修正口径分别保留。

新用途flag的五个真实生产管线案例中，前四个首答的schema、空reply、动作策略、素材与公开回复通过。第五个首次arguments出现嵌套对象，随后沿用正式message既有第二次格式修复，通过schema、空reply和4人10线索更正材料保留。初答与续验分别记录，共5次首答与1次既有格式修复，未创建剧情生成job。结果限于这组固定输入。详见 [pipeline-assessment.json](task20-role-package/production-intent-controls/pipeline-assessment.json)。

## 自动测试与产物指纹

最终源码完整 `pytest -q` 为812项通过、36.35秒，保留1项既有Starlette/httpx弃用提示。12项intent与退出相关回归通过、10.26秒。

PyInstaller构建105.81秒。归档内18个项目模块与源码编译code object相同，33个前端、正式案件和设置资源逐字节相同。ZIP CRC、交付文件及密钥与用户配置排除检查通过，root另行复核2580条目CRC和实际私钥排除通过。详见 [automated-tests.json](task20-role-v2/automated-tests.json) 与 [build-provenance.json](task20-role-v2/build-provenance.json)。

## 最终EXE真实批次

本机实际EXE在PATH仅含Windows系统目录的环境执行，本机安装有Python。默认APPDATA隔离子根首次设置、三个原生菜单、对局与编剧记录跨随机端口恢复通过，实际虚拟与MSIX物理路径分列在 [default-appdata.json](task20-role-v2/default-appdata.json)。三个任务19人工修订演示案开局及重启恢复通过，保留true，SDK调用0，见 [exe-samples.json](task20-role-v2/exe-samples.json)。

OpenAI实际连接、招牌案两回合与重启恢复通过。原始校园书店输入完整保留，素材判意21.23秒后成功，经“全新”“精修”确认创建唯一质量生成job。

首轮两份候选各到540秒无正文，实际541.65及541.51秒，提供方同ID取消200，事后只读retrieve均为cancelled。第二轮正常继续设计，429.40秒返回，随后演员同设计填表46.07秒及字段修复41.45秒。设计审稿5.19秒、只给汤面盲答10.16秒、全部线索盲答5.88秒后全部检查结束。首轮没有取得两份完成稿，候选比较的实际结果为两个超时后进入正常下一轮。详见 [provider-design-status.json](task20-role-v2/provider-design-status.json) 和 [generation-step-ledger.json](task20-role-v2/generation-step-ledger.json)。

原卡片前端完整计时1076.293秒后done，生成《空白本》，实际3人、8线索、2谎话、3题、2结局，自动checked:true。真正等待done并点击原卡片“开始调查”，李岚和周竞各一次真实问话20.70及21.71秒，两回合记录及原checked在重启后恢复，原卡片仍done。再通过首页目录真实按钮新开同案，原局仍可读取。实际问话及端口见 [exe-live.json](task20-role-v2/exe-live.json)。

新生成设计已获ID后窗口关闭，20.86秒自然退出0，原ID取消200，重启故事集相同且没有tmp半稿。素材对话active状态已获ID后关窗，ASGI等待30秒后取消请求，原ID取消200完成后才结束应用关闭，50.18秒自然退出0。再次启动故事集相同，QA配置已替换假key。全过程没有强杀，见 [shutdown-events.json](task20-role-v2/shutdown-events.json)。

《空白本》原稿、所选第二轮设计及指纹保留，结构、编译、指定规模、设计填表一致性和好玩度问题列表均空。离线使用同版引擎执行27种结案答案组合，26种错误组合进入可重试结局，完整真相0。见 [generated-case-checks.json](task20-role-v2/generated-case-checks.json)。

额外桌面样本的人工定向复核确认P3分钟不一致。设计区间19:41至19:42可容纳拍照和两次发送，但correction及f8/f9精确写19:42搬书，与c8记19:41已发同图冲突，三题均不依赖这个精确分钟。原自动true保留，该样本人工全文质量验收未通过，完整真实角色调查也未执行。任务18两份已验收案件的整局证据另列，本样本只承担本轮桌面生成与基础交互复验。见 [narrative-review.json](task20-role-v2/narrative-review.json)。

## 产物

最终ZIP为 `D:\阅读周比赛\看山谜案馆-质量收敛交付版-20261104-v2.zip`，SHA256为 `8854a4561555bca867dbfeb908d2557d1ca232186e0f6c252c438772d40eee9f`，46,998,487字节。EXE SHA256为 `03228edbe1a5816689030fd3a9c20fd9cbdcbd312b029b8dc4ff5ccf82731b39`。首版ZIP与中间候选分别保留，交付含三份已人工修订验收的演示案，checked均沿用true。

## 已知问题

- 另一台未安装Python的Windows电脑完整流程尚待用户实际操作。
- 额外生成《空白本》存在P3局部分钟不一致，人工全文质量验收未通过，完整真实角色调查未执行。
- 本次精修首轮双候选均到540秒无正文，后续第二轮完成，首轮没有形成两份完整候选比较。

## 外机最短步骤

1. 在Windows10/11 x64全部解压ZIP，双击看山谜案馆.exe，按提示安装WebView2 Runtime。
2. 模型设置选择OpenAI，两模型填gpt-5.4-2026-03-05和自己的key，测试连接后保存。
3. 招牌案开局问话两回合，退出重开确认记录恢复。
4. 新建剧场粘贴原书店输入，回复全新、精修，等待卡片完成，记录用时和质量提示，点开始调查。
5. 两名角色各问一次，退出重开确认同局和原done卡片恢复。
6. 新生成已进入设计时关闭重开，确认原存档和旧案完整、没有半份新稿。将日志与实际结果交回核验。
