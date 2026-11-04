# 任务18质量收敛验收

## 本轮现状

最新正式续修的生成与演员源码均为 `084b67e0f6162cd165e518da4fd284aec82d9407`。医院18步、书店20步正常HTTP真实角色整局完成，核心证据、严格改口阶段、说话主体和秘密检查通过。医院原始自动checked:false保留，书店原始自动checked:true保留。医院录音笔位置及书店追回日期两项P2在正式新设计与实际材料中得到修正；书店第2步“今晚”为P3相对时间措辞，继续保留。最终审稿复核运行源码为 `38e91999c50b2ee02251148e38d270a42b337b43`，800项测试通过，生产函数四例真实schema与索引全部通过。医院据后续正式复核与严格整局验收另建checked:true的tested-story副本，仅改变该字段，原false及其审稿记录完整保留。生成、演员与后续审稿复核版本分别记录。

本轮从 `origin/main` 的 `bc4d9ef2c4cfa8cfd90ec80f6a7804777bca6db1` 新建任务18分支。PR #38、#39、#40 已合并，后续工作使用新分支和独立PR。任务21继续暂停，PR #36保持扩展草稿。

上轮医院197.45秒、书店166.31秒均为DeepSeek HTTP402中断后的保稿用时，两案checked:false，分别安排的两次真实角色问话也被402阻断。这两项仅记录中断耗时，正常完成速度验收仍缺结果，原始基线见 [上轮验收报告](2026-11-04-task18-final-acceptance.md)。本轮完整生成、正式续修与真实角色整局采用各自的新记录。

修订前候选为《旧楼M-17》和《B-3里的空白书》，原稿保留在pre-revision。前者使用快速档，第4批选中第2轮，19步整局通过；后者使用既有精修双候选流程，首轮选中候选1，21步整局通过。早期DeepSeek医院缺证与误报、OpenAI自动true但人工发现问题、服务502中断及书店快速稿未达项全部作为诊断保留。

| 批次 | 输入 | 生成耗时 | 自动结果 | 人工证据与实际试玩 |
|---|---|---:|---|---|
| DeepSeek最终对照 quality-live-3 | 医院 | 361.61秒 | checked:false | 完整真相仍有缺证，审稿有误报，未完成真实整局 |
| DeepSeek最终对照 quality-live-3 | 校园书店 | 321.25秒 | checked:true | 3人8线索2谎话3题2结局，OpenAI演员12步整局、3/3结案、实际错答进入retry结局 |
| OpenAI非流式 quality-openai-1 | 医院 | 465.02秒 | failed，无剧本 | 设计连续超时及连接失败 |
| OpenAI非流式 quality-openai-1 | 校园书店 | 主动停止 | cancelled | 同类传输问题定位期间停止后续调用 |
| OpenAI后台轮询 quality-openai-2 | 医院 | 476.72秒 | checked:true | 人工发现f14无锁事实与f15改口错配，真实试玩3步成功、第4步502，complete:false |
| OpenAI后台轮询 quality-openai-2 | 校园书店 | 255.77秒 | failed，无剧本 | 设计247.78秒，填表7.51秒后连接失败 |
| OpenAI修正契约 quality-openai-3 | 医院 | 370.13秒 | checked:false | 只给汤面3/3，腕带辅助证据被误报，600秒预算下未再修订 |
| OpenAI修正契约 quality-openai-3 | 校园书店 | 359.55秒 | checked:true | 设计的挽回/追责方向与实际完整+retry结局存在偏离 |
| OpenAI模型配置调整后 quality-openai-4 | 医院 | 1183.24秒 | checked:true | 选第2轮，19步9/9线索3/3谎话全秘密开放，3/3结案，保留录音笔物品流转小缺口 |
| OpenAI模型配置调整后 quality-openai-4 | 校园书店 | 940.89秒 | checked:false | 保留第1轮，最深线索仅第2层，人工另发现初始同义事实裸露与定位材料顺序问题 |
| 既有精修双候选 quality-openai-fine-1 | 校园书店 | 418.82秒 | checked:true | 首轮双候选选中1，21步8/8线索2/2谎话全秘密开放，3/3结案 |

原始请求响应、每步时间和失败记录按批次保留，文件指纹统一写入 [manifest.json](task18-quality/manifest.json)。正式第4批及追加精修批全量作为诊断保存，原两份选中稿另存pre-revision。最新来源为revision2的两份正式续修稿，模式、运行版本和累计时间按provenance单列，原生成稿、最终设计及真实整局记录一一对应。

## 动态口供复核后的追加修复与再验

19步医院与21步书店记录对应b02生成及当时的角色实现。后续逐句复核发现医院第15步秦岳在对应谎话尚未拆穿时就直接改口，书店第11步唐芮把林沅“我把0719卡借给赵澄”的第一人称事实套成自己的持卡经历。原稿自动checked:true及初次路线记录完整保留，动态口供另行验收。

追加修复提交 `5c2a7ceaf04e059067ffbaaee313c9dfa5a036eb`，751项自动测试通过。核查继续按active_lies控制本人改口阶段，引擎上下文为唯一lies.admit来源的第一人称事实增加first_person_subject，演员与核查通过白名单传递id/name主体信息，原事实id/text与许可集合保留。

医院与书店的先前固定回合用于定位提前改口和主体误认。书店主体标注后的首轮控制仍曾漏检，原“18:52前都不在我手里”被放行，passed:false，原始请求与输出保存在 [subject-attribution-trial1/bookstore.json](task18-quality/actor-turn-controls/subject-attribution-trial1/bookstore.json)。

最终角色修复源码为 `084b67e0f6162cd165e518da4fd284aec82d9407`，完整774项自动测试通过，39.85秒。极窄第一人称护栏保留明确第三方表述和授权改口，含显式引号的事实沿用原引语说话人。两例真实固定控制均通过，医院26.21秒、书店10.94秒，原错误候选被拦截，正常回复与解锁后正例通过，见 [医院控制](task18-quality/actor-turn-controls/hospital.json) 和 [书店控制](task18-quality/actor-turn-controls/bookstore.json)。

三份既有演示案在084b67e下通过最终新上下文离线全局兼容回归。92次_context与b02逐字段对照，剥离新增主体后原id/text、许可及其他上下文一致；实际演员与核查构造的82份payload白名单通过。46步公开输出、初始及最终权限、取证拆谎、结案与错答隔离均与原真实验收记录一致，模型调用0，YAML指纹保持原值，见 [demo-role-compatibility.json](task18-quality/demo-role-compatibility.json)。

最终38e9199再次运行同一回归，92次上下文、82份payload、46步公开结果及全部错误结局检查通过，真实模型调用0。当前demo-role-compatibility固定该最终源码，演员与引擎内容沿用084b67e，三案剧情与原许可集合一致。

兼容复核发现《末班车的干伞》f_liang_chat原本包含梁、苏各自的第一人称引语。084b67e已排除给该条聊天事实附加单一第一人称主体，保留原引语说话人；最终92次上下文、82份payload与46步公开结果复核通过。先前主体风险证据保存在 [pre-quoted-exclusion.json](task18-quality/demo-role-compatibility/pre-quoted-exclusion.json)，最终结果见当前demo-role-compatibility。

用户已合并PR #41和#43，新增角色修复与桌面v2从最新main继续独立交付，原PR记录保留。三份演示案YAML沿用已验收版本。

## 原始输入与模型设置

医院使用原始输入“我想玩恐怖一点的，医院题材”。

校园书店使用原始输入“我想玩一个现代校园书店里的案子：闭店后，一本预订书被换成了空白本。请改编成3个人、8条线索、2句谎话、3个结局题、2个结局的短篇现实推理，线索能相互印证，人物动机清楚。”。

DeepSeek对照的编剧和演员均为 `deepseek-flash`，编剧开启思考并使用high，演员关闭思考。high恢复为质量对照基线。既有low与本轮high的提示、修复和服务状态有差异，同条件质量比较需要独立完整样本。

按用户提供的OpenAI接口追加账户支持的 `gpt-5.4-2026-03-05` 快照对照，编剧high、演员none。用户指定文本的物理第6行为空，实际读取open-ai标记对应的凭据，私有值由本机配置保管，验收材料仅记录模型与请求参数。DeepSeek生成稿的后续实际角色试玩使用OpenAI演员，生成与试玩的服务来源分别记录。角色使用的模型设置以各批 `wire-model-checks.json` 及对应执行记录为准。

运行版本分别对应 DeepSeek对照 `30180444163ea3df16ce4014dde5fd4bbbd9d32b`、OpenAI非流式 `1d48752e1845acb77db3fbdd537a5057c2fd7ddb`、OpenAI后台正式批 `022f9f46e597adcd9baa0a06ff379562abd5b7e8`。第3批源码为 `d2813a53686ef1472eb58e22c45a7f071104a380`。模型配置预算调整后的最终第4批源码为 `b02f0c5515355f0f7e87f1b6114ba6aa70a0e735`。

## 本轮修复与正式流程

- 恢复DeepSeek编剧high，保留演员关闭思考，以及字段成员合并、完整裸设计解析、证据别名、秘密锁、坏稿与超时保稿。
- 填表核对设计与用户指定规模，检查新增或遗漏线索、人物和题目。固定坏稿中，设计8线索而填表9线索会进入同设计填表修复。
- 核对设计中的必要证据和取得条件，包括组合条件、出示与持有的区别，以及发放事件的取得路径。取件通知和承认记录的前置遗漏有固定案例回归。
- 核对同一秘密或证据事实在其他角色的无锁副本，补查 `lies.admit` 直接开放同一fact、绕过较强 `secrets.until` 的情况。自然语言设计明确要求改口直接纠正原谎话，额外动作各保留证据与秘密锁。
- 审稿仍只审设计并返回问题列表。错误选项允许被证据排除，作者私有时间线按后台材料处理。身份、实际动作、直接承认、完整真相的因果与取得链继续逐项复核。

正式流程继续采用编剧开思考写自然语言设计、演员关思考填表。格式、引用和编译一致性问题保持设计不变，首次填表后最多重试两次，程序检查通过后结束填表。好玩度、设计审稿和两次可解性检查的质量问题进入下一轮设计修订。

OpenAI长设计调用改用Responses后台任务轮询，记录同一response ID的状态和正文。官方OpenAI编剧单次期限调整为540秒，整体预算按模型配置区分，演员继续使用none的JSON调用。连接失败和超时的恢复、取消与保稿按最终源码回归验收，具体接口约定见SPEC。

## DeepSeek high最终对照

### 医院《负一层治疗室》

生成361.61秒，前置对话5.14秒，自动保留第1轮设计及其填表，checked:false。程序结构和好玩度通过，选中稿的设计对应检查为空问题列表。第2、3轮填表继续出现程序问题，最终保留先前可运行稿。

审稿要求补“刷卡片正面N-07”才能证明苏婉本人刷门，但题目询问实际刷门者，走廊视频已经明确记录苏婉刷门。审稿又要求在病历承认中补“约1:50推药”，而原材料已经包含这句承认。问题列表中还包含“第3题成立、链条可执行、无需报错”的文字。以上原始警告保留供校准。

人工复核另发现完整真相断言“过量注射致死”。可获材料包含新鲜针眼、临时医嘱与推药承认，正文缺少对应的剂量与死亡因果证据。该项继续列为剧情缺证。审稿误报消除后仍需独立核对完整真相。

原始数据见 [结果](task18-quality/comparisons/deepseek-final/hospital/result.json)、[选中设计](task18-quality/comparisons/deepseek-final/hospital/selected-design.json)、[剧本](task18-quality/comparisons/deepseek-final/hospital/story.yaml) 和 [步骤](task18-quality/comparisons/deepseek-final/hospital/steps.json)。

### 校园书店《群山回声的空白本》

生成321.25秒，前置对话5.67秒，自动选中第3轮，checked:true，程序、好玩度、设计对应和生成流程的两次可解性检查通过。最终规模为3人、8线索、2句谎话、3题、2结局。

| 题目 | 标准答案 | 可获证据 |
|---|---|---|
| 21:12和21:20使用谁的卡、摄像头拍到谁本人 | 周岚的员工卡和本人 | c_backdoor《后门门禁与楼道监控记录》同时记卡号Z-027、登记周岚及其本人在读卡器前刷卡 |
| 放空白本并取走真书的时段 | 21:16—21:18 | c_camera《后场监控21:16—21:18》直接记录调换和藏书动作 |
| 21:17指使把真书放入纸箱夹层的人 | 林澄 | c_wechat《林澄指使藏书的微信》有发信人、21:17原话和21:18回复 |

后续使用OpenAI演员完成12步真实HTTP路线，取得8/8线索、拆穿2/2谎话、全部秘密开放。该案事件数组为空，实际路线包含取证、出示、拆谎、改口、追问秘密和结案。按剧本标准答案实际提交为3/3，完整真相retry:false。实际一题错为2/3、全错为0/3，均进入“证据不足”且retry:true。

末尾林澄实际承认21:17发微信让周岚藏真书，21:16至21:18人在后场并看见调包未阻止。周岚实际更正“打烊后没再回来”，承认21:12后门返回、21:16调换、21:18按微信藏书、21:20离店。许知遥实际承认20:58进过柜台内侧拍照，并说明此前隐瞒代订及差价。

原始数据见 [结果](task18-quality/comparisons/deepseek-final/bookstore/result.json)、[设计](task18-quality/comparisons/deepseek-final/bookstore/selected-design.json)、[步骤](task18-quality/comparisons/deepseek-final/bookstore/steps.json) 和 [实际完整试玩](task18-quality/comparisons/deepseek-final/bookstore/playthrough.json)。

## OpenAI传输诊断与正式批次

### 非流式、SSE与后台取回

非流式医院设计第1、2次分别180.01秒超时，第3次104.92秒后连接错误，总生成465.02秒，无剧本。书店后续调用主动停止并保留interrupt记录。原始结果见 [非流式医院](task18-quality/diagnostics/quality-openai-1/hospital/result.json) 与 [书店停止记录](task18-quality/diagnostics/quality-openai-1/bookstore/interrupt.json)。

SSE诊断162.01秒后APIConnectionError，接收chunk数和正文字符数均为0。后台诊断先取得response ID，在330.01秒时本地等待结束，随后继续查询同一ID，最终取回完整设计，服务端耗时405.59秒。该记录只覆盖一次设计请求，完整填表、审稿、盲答及实际整局均未执行，独立审阅记录的设计缺项随诊断留存。

后台取回沿用原response ID，后续状态查询单独留档。原始记录见 [SSE诊断](task18-quality/diagnostics/openai-stream-probe/result.json)、[后台首次等待](task18-quality/diagnostics/openai-background-probe/result.json) 和 [同ID取回结果](task18-quality/diagnostics/openai-background-probe/retrieved-result.json)。

### OpenAI后台正式医院《冷库尸行》

生成476.72秒，前置对话11.41秒，选中第2轮，自动checked:true。程序结构、好玩度、设计对应、审稿和两次可解性检查均返回通过。该自动结果逐字保留，人工复核判定未合格。

人工复核发现f14“顾闻22:54签字借出氧气瓶扳手”直接出现在罗恪与顾闻的knows中，开局无秘密锁，证据事实可在取得《维修工具借出单》前公开。顾闻谎话l3为“我没碰过氧气瓶扳手”，admit指向f15“前往B1拆停用氧气阀和铜件”，没有直接纠正碰过或借过扳手的原断言。后续c9补充口供虽然明确借扳手和击打，拆谎当下的admit仍需修订。

该次真实试玩记录3步成功。第4步向罗恪追问材料返回API502，complete:false，记录停留于全部秘密开放与结案前。原始结果见 [自动检查与耗时](task18-quality/diagnostics/quality-openai-2/hospital/result.json)、[实际剧本](task18-quality/diagnostics/quality-openai-2/hospital/story.yaml) 和 [中断的实际试玩](task18-quality/diagnostics/quality-openai-2/hospital/playthrough.json)。

### OpenAI后台正式校园书店

设计调用247.78秒成功，演员填表7.51秒后连接失败，总生成255.77秒。该次没有可发布剧本，checked为空。失败前的设计和填表请求保留，参见 [步骤](task18-quality/diagnostics/quality-openai-2/bookstore/steps.json)、[结果](task18-quality/diagnostics/quality-openai-2/bookstore/result.json) 和 [填表失败请求](task18-quality/diagnostics/quality-openai-2/bookstore/failure-001.json)。

## OpenAI第3批诊断与预算调整依据

第3批医院生成370.13秒，前置对话24.64秒，保留第1轮，自动checked:false。只给汤面即3/3，难度检查真实未通过。审稿另将第2题的《患者腕带》作为缺陷，尽管《护士站对讲录音》已完整记录被询问的报告内容，腕带仅作辅助印证。该冗余证据误报与真实难度问题分别保留。首轮完整用时之后，600秒预算中的剩余时间不足预测的下一完整轮，流程保留带警告稿，原始数据见 [医院结果](task18-quality/diagnostics/quality-openai-3/hospital/result.json)。

第3批校园书店生成359.55秒，前置对话15.74秒，选中第2轮，自动checked:true。设计truth规划“查明调包者与藏匿处即挽回、再坐实转卖计划与房租动机则追责”两个方向，实际填表的结局为全对追责与未全对retry，设计方向与实际执行存在偏离。原始自动true保留，人工复核的结局方向未达项单列，参见 [书店结果](task18-quality/diagnostics/quality-openai-3/bookstore/result.json) 与 [选中设计](task18-quality/diagnostics/quality-openai-3/bookstore/selected-design.json)。

按实际整轮用时和用户授权，官方OpenAI GPT-5.4配置的快速/精修总预算改为1200/1800秒，快速仍最多3轮，精修轮次与双候选流程沿用既有规则。DeepSeek继续600/900秒。新文案说明精修比较两份设计并增加修订轮次，实际耗时取决于素材和模型。预算调整由任务18实现，新旧问句的前端按钮兼容由任务19独立PR验收。

新review契约加入“对讲录音已完整证明报告内容、腕带辅助印证无需删证据”的正例，同时继续检查真实缺证。设计契约明确用户未指定其他规则时，默认规划全对完整真相和证据不足可继续调查两个方向，完整结局可同时包含追回与追责。后续实际生成与完整试玩结果分别保留在第4批和精修批的原始记录中。

## 固定请求与审稿契约对照

书店对照逐字复用上轮的同一填表messages，将调用模型改为OpenAI演员none。31.73秒返回3人9线索2谎话，仍超出原设计8线索。新的设计对应检查还检出出示被替换为持有、取件通知及承认记录遗漏预订登记单前置。该固定旧请求下，换模型后仍会发生相同类别的填表偏差，记录见 [bookstore.json](task18-quality/openai-fixed-controls/bookstore.json)。

医院旧审稿对照逐字复用上轮审稿messages。OpenAI演员none在10.00秒返回缺证问题，同时把私有时间线当成可能向玩家公开的材料而报提前泄底。新review契约对照保留相同user设计，只替换系统审稿契约，5.99秒返回1项动作身份缺证，先前私有时间线误报消失，原苏雯本人刷卡的缺证仍未全部报告。两个请求的系统契约差异单独记录，参见 [旧请求](task18-quality/openai-fixed-controls/hospital.json) 和 [新契约](task18-quality/openai-fixed-controls/hospital-current-review-contract.json)。

三类固定校准分别覆盖正确干扰项、卡号缺身份、改口与原谎话错配。DeepSeek在3018044、OpenAI在022f9f4的三例均与预期一致。真实生成稿仍出现误报或漏检，固定校准与开放题材的实际审阅分别保留。校准记录见 [DeepSeek](task18-quality/reviewer-3018044/valid_distractors.json) 与 [OpenAI](task18-quality/reviewer-openai-022f9f4/valid_distractors.json)，同目录另存两个真实缺陷用例。

现有对照同时包含模型切换、审稿契约修订和传输修复。模型质量比较仍需同条件完整样本，当前报告保留每次请求与具体错误类别。

### 同接口思考对照与具体指控复核

审稿契约a5c0c68的三个固定输入在同一GPT-5.4模型、同一Responses后台接口、相同messages和540秒单次期限下分别使用none和high。none三例均完成且与预期一致，正确医院为19.89秒、改口错配为76.94秒、卡号缺身份为10.77秒。high的两个真实缺证负例分别55.72秒和26.64秒完成且检出对应缺陷；正确医院始终queued，达到540秒期限后取消，墙钟542.36秒，取消返回HTTP200。该正例没有正文和质量结果，当前无法据此判定high的正确医院审稿质量。每个输入每档只有一次，固定对照见 [comparison.json](task18-quality/reviewer-thinking-control/comparison.json)。

另有一次Chat-none具体指控复核实验，以已存在的问题列表为核实对象，四例的保留索引全部符合预期。原实验同时要求解释引文，其中正确医院与卡号缺身份两例未做到逐字引用，完整旧schema仅2/4符合，all_matched:false继续保留。该实验分别记录索引选择与引文契约，不能将四例索引正确写成旧schema整体通过，见 [summary.json](task18-quality/reviewer-issue-verification/summary.json)。

38e9199正式实现将复核输出限定为严格JSON的keep_indices列表。仅初审问题非空时，使用演员none对原设计及这些具体指控追加一次复核；空初审直接结束，新增调用数为0。索引必须为不重复且不越界的整数，输出格式错误或超时保留原问题并附“审稿复核未完成”标识，402沿既有流程停止后续批量调用。正式输出仅要求保留索引，解释引文不属于本次输出字段。800项自动测试通过。

正式生产函数StudioService._verify_review真实四例的严格schema及索引均通过，未触发fallback。正确医院两项误报全部删除，用时18.97秒；卡号缺身份保留两项原缺陷，用时2.83秒；改口错配保留原缺陷，用时4.97秒；首次医院修订中的焚化目的缺证仍保留，用时6.67秒。正确稿、两类固定真缺证和实际历史目的缺口分别校准，原始请求、输出与模型记录见 [summary.json](task18-quality/reviewer-production-verification/summary.json)。医院在38e9199下的当前策略复核问题列表为空，程序、好玩度、设计对应、可解性和18步整局分别通过，来源指纹见 [reassessment.json](task18-quality/reviewer-production-verification/reassessment.json)。

## 修订前两案与原始真实完整试玩

### 医院《旧楼M-17》

第4批医院使用快速档，生成1183.24秒，前置对话86.23秒，选中第2轮，自动checked:true。程序结构、好玩度、设计对应、审稿及两次可解性检查通过。独立审阅的核心证据、改口对应和秘密锁通过。

正常HTTP入口的新局完成19步真实角色调查，取得9/9线索、拆穿3/3谎话，全部秘密开放，实际提交3/3进入“封住焚化间通道”，retry:false。末尾苏芮更正一点后一直在护士站的说法，承认01:16去过旧楼并取回录音笔；程坤承认01:18推出M-17、01:29按秦岳指示继续转移；秦岳承认01:24进入旧手术室、01:25用氧气瓶击倒罗衡、亲手更改顾南登记及2023年违规加快镇静滴速。

录音笔从病号服夹层到遗体袋夹层的流转未交代，保留为小叙事缺口。该项与已完成的取证、拆谎、秘密开放和结案分别记录。

原始结果与逐步耗时见 [生成结果](task18-quality/pre-revision/hospital/result.json)、[生成步骤](task18-quality/pre-revision/hospital/steps.json) 和 [完整真实试玩](task18-quality/pre-revision/hospital/playthrough.json)，逐题依据及实际口供映射见 [证据表](task18-quality/pre-revision/hospital/question-evidence.json)。

### 校园书店《B-3里的空白书》

第4批快速书店生成940.89秒，最终保留第1轮，checked:false。最深线索仅第2层，人工另发现开局同义事实裸露和定位材料顺序问题。该稿保留为诊断，见 [快速书店结果](task18-quality/diagnostics/quality-openai-4/bookstore/result.json)。

随后使用既有精修流程，首轮并行比较两个候选，选中候选1，418.82秒完成，前置对话20.70秒，自动checked:true。最终规模为3人、8线索、2句谎话、3道题、2个结局。精修按既有最多4轮/1800秒规则执行，本案在首轮完成检查。

正常HTTP入口的新局完成21步真实角色调查，取得8/8线索、拆穿2/2谎话，全部秘密开放，实际提交3/3进入“追回真书”，retry:false。末尾林沅承认18:42借出0719卡及此前隐瞒的违规借卡；赵澄承认18:48打开B-3取出真书并塞入空白样书；唐芮承认提出支付200元借书一晚，并在21:12把真书存入校内快递柜7号、收件人写赵澄。

原始结果与逐步耗时见 [生成结果](task18-quality/pre-revision/bookstore/result.json)、[生成步骤](task18-quality/pre-revision/bookstore/steps.json) 和 [完整真实试玩](task18-quality/pre-revision/bookstore/playthrough.json)，逐题依据及实际口供映射见 [证据表](task18-quality/pre-revision/bookstore/question-evidence.json)。

### 正确结案与错误答案隔离

| 验收项 | 医院，快速 | 校园书店，精修 |
|---|---|---|
| 运行commit | b02f0c5 | b02f0c5 |
| 生成耗时 | 1183.24秒 | 418.82秒 |
| 选中稿 | 第2轮 | 首轮双候选中的候选1 |
| 自动checked | true | true |
| 程序、好玩度、设计审稿与双盲 | 通过 | 通过 |
| 真实调查步数 | 19 | 21 |
| 已取线索 | 9/9 | 8/8 |
| 已拆谎话 | 3/3 | 2/2 |
| 最终锁住的秘密 | 0 | 0 |
| 实际正确结案 | 3/3，retry:false | 3/3，retry:false |
| 实际一题错与全错 | 2/3和0/3，均retry:true | 2/3和0/3，均retry:true |
| 选项穷举 | 27组合，完整真相1种，错答进入0 | 64组合，完整真相1种，错答进入0 |
| 人工核心证据复核 | 证据、改口对应及锁通过，录音笔流转叙事未达 | 指定规模与证据链通过，追回时间叙事未达 |
| 084b67e真实固定控制 | 提前认错已拦截，解锁正例通过 | 主体误认已拦截，正常回复及解锁正例通过 |

两案事件数组均为空，实际路线覆盖取证、出示、拆谎、改口、秘密开放和结案。结案按剧本标准答案实际提交，角色问话、出示及追问均为真实模型调用。原始完整真相和retry结局文本、全部选项组合计数保存于各案result，实际一错、全错的HTTP提交结果保存于playthrough。

两个最终案例分别使用快速和精修，素材也不同。耗时用于说明各次完整流程，首轮精修并行步骤的耗时单列在steps，整轮墙钟时间以result为准。

### 修订前两项叙事复核未达

独立核对原设计、事实与结局后，两项均保留P2叙事问题。精确原文、字段位置、原稿指纹及建议修订方式见 [narrative-review.json](task18-quality/narrative-review.json)，原始YAML与设计未改。

医院设计时间线写“顾南录下银色录音笔并把它藏进病号服夹层”，随后又写苏芮带着“从遗体袋夹层取出的银色录音笔”离开。两个容器位置不同，原文没有给出转存者、时间或动作。现有文本容许中间发生一次转存，因此足以确认流转说明缺项，尚不足把它认定为物理上互相排斥的事实。录音笔取得过程的连贯性仍需补齐，三道人物动作题的既有依据分别保留。

书店原时间线和f6明确“2026-04-18 09:10……事件暴露”，开锁日志在同日09:34才导出，结局却紧接4月17日21:12的寄存叙述写“凭寄存截图，你们当晚就能追回真书”。按案发当晚解读，追回会早于调查发现，顺序不成立；若指4月18日调查当晚，原文仍缺明确日期。该处属于结局时间指代未消除的冲突与歧义，实际追回时间需要修订说明。三道回溯题的答案支持与这项未达叙事分别记录。

### QA驱动脚本首次失败与更正

医院首次试玩的驱动器把“信任度低于3”作为通用选人条件，反复选择苏芮，最终归档51步仍只取得c1/c2/c3，complete:false。该次QA失败归因驱动器的选人条件，原记录独立保留为 [playthrough-driver-trial1.json](task18-quality/pre-revision/hospital/playthrough-driver-trial1.json)。

更正后，驱动器只对当前线索明确要求而尚未满足的trust门槛安排交流，再沿可执行出示路径推进。重新建立的新局完整19步通过，旧记录与新局记录分别留档。

### 修订前来源与指纹

修订前来源为 `.cache/quality-openai-4/hospital` 与 `.cache/quality-openai-fine-1/bookstore`，实际原目录、fast/fine、运行commit、生成结果与原稿指纹写入manifest的pre-revision记录。第4批和精修批全量另存diagnostics。选中设计、实际填表请求、剧本和真实整局记录按同一案件关联，原始请求响应保持完整字节。final/provenance对应最新revision2来源。

原b02f0c5阶段完整pytest为739项通过，当时合并集成版本743项通过，这两项属于修订前历史验收。当前任务18的38e9199为800项通过；最终合并源码df344149包含任务20的752提交，完整803项通过，66.58秒，保留一条既有Starlette warning。桌面最终产物与源码一致性、本机完整流程及另一台未安装Python的Windows电脑流程由任务20独立记录。任务21继续暂停。

## 正式设计修订与演员再验

两项P2叙事未达触发正式下一轮设计修订。首次修订目录为 `.cache/quality-openai-revision/{hospital,bookstore}`，原样作为trial1保留；定向重试使用全新 `.cache/quality-openai-revision2/{hospital,bookstore}`，沿用原始输入，携previous_design和具体问题重新调用编剧设计，再执行演员填表、设计审稿、好玩度与双盲检查。原始b02设计、剧本及19/21步记录按原字节保留在pre-revision。修订稿的生成runtime由各自result记录，角色修复源码为084b67e。

修订后的新生成结果及正常HTTP入口整局验收继续单独记录。早期隔离演员目录 `.cache/actor-final-replay/{hospital,bookstore}` 保留原修订前材料；最终两案实际试玩位于 `.cache/quality-openai-revision2/{hospital,bookstore}`。最终采集显式指定revision2为actor-dir，将对应playthrough收录为actor-replay，避免沿用旧剧本的回放。新playthrough记录generation_runtime_commit、actor_runtime_commit以及实际故事与设计指纹，逐题证据表绑定当前原始材料和对应演员回放，生成、演员及后续审稿复核源码单列。

当前两固定控制与三份既有演示案离线兼容已通过。正式设计修订后的两项叙事、完整真实整局及最终桌面v2验收以新记录为准，旧稿两项P2仍保留未达状态。

### 首次正式修订的独立核对

医院的录音笔位置已在新design的truth、timeline、苏芮secret与c7统一为“M-17所穿病号服夹层”，c7新增苏芮签字确认01:27从该位置取出，填表保留同一正文。原容器转移缺项在本次设计与填表中消除。

新审稿针对q3“以掩盖顾南身份”目的分句报告缺证。独立复核认为该警告部分成立。c6明确秦岳下令“把17号先送焚化间”，c9确认按秦岳指示转移，下令者直接成立；c8有秦岳本人将顾南改登记为M-17的签名，秦岳知悉身份也有材料，审稿这一部分漏读。罗衡当场喊“你这是灭证”与旧更名记录支持灭证推论，仍未明写当晚焚化与隐藏顾南身份之间更窄的目的关联。保留目的分句时继续由正式设计补清楚公开依据，证据形式可为录音、记录或可靠供述。

首次书店修订设计将追回明确为“在4月18日事件暴露并调取证据后”，时间线同时记录4月18日09:10发现、09:34导日志。时间问题在这一轮设计文字层得到修正，首轮设计返回唐芮evidence:null，违反str契约，revision148.43秒后failed，story为空；该次未进入填表与整局验收。后续revision2的填表和整局结果单独列于下节。

精确正文和原始文件指纹见 [revision-design-review.json](task18-quality/revision-design-review.json)。首次修订结果按自动状态保留，后续正式修订与演员整局继续独立记录。

## 最新正式续修与真实整局结果

最终两案来自 `.cache/quality-openai-revision2/{hospital,bookstore}`，生成与演员runtime均为084b67e。修订保持原输入及原核心事件，人工问题通过编剧设计、演员填表及完整质量检查处理，原生成稿与pre-revision的19/21步严格失配记录独立保留。

| 项目 | 医院新版 | 校园书店新版 |
|---|---|---|
| 当前模式 | 人工审稿后的精修续修 | 人工审稿后的精修续修 |
| 最近续修耗时 | 329.76秒 | 204.93秒 |
| 可追溯累计生成耗时 | 2268.55秒 | 772.18秒 |
| 原始自动checked | false | true |
| 验收后质量标记 | tested-story副本true，原story与result仍false | 原稿true保留 |
| 程序、好玩度、设计对应及双盲 | 通过 | 通过 |
| 原审稿 | 保留误报列表 | 空问题列表 |
| 真实HTTP调查 | 18步，236.96秒 | 20步，254.46秒 |
| 已取线索 / 已拆谎话 | 9/9，3/3 | 8/8，2/2 |
| 最终锁住秘密 | 0 | 0 |
| 实际正确结案 | 3/3，retry:false | 3/3，retry:false |
| 实际一错 / 全错 | 2/3与0/3，均retry:true | 2/3与0/3，均retry:true |
| 全选项枚举 | 27种，错答进入完整真相0 | 64种，错答进入完整真相0 |
| 逐句阶段 / 主体 / 秘密 | 通过 | 通过 |
| 原两项P2 | 病号服夹层位置统一，取笔签字与实际口供一致 | 结局明确4月18日发现及取证后追回 |
| 其余措辞问题 | 本轮核心逐句复核未新增 | 第2步沿用profile的“今晚”，P3保留 |

医院时间链为原始快速1183.24秒、录音笔连续性修订755.55秒、最新精修续修329.76秒，累计2268.55秒。书店为原精修418.82秒、追回日期修订的设计类型失败148.43秒、最新续修204.93秒，累计772.18秒。每次均按该次档位单独记录，续修耗时与累计耗时分列，逐步模型时间以各自steps及timing_lineage为准。

医院第14步只向秦岳出示c6时，其l3仍active，实际回复为回避。第15步出示c5后才直接更正进入旧手术室并交c8，原提前认错消除。苏芮第16步明确说从“M-17所穿病号服夹层”取笔，程坤第13/17步确认秦的当面命令。秦末尾仅承认进入，没有额外口头认伤人与下令，q1由直接视频及检材、q3由对讲录音及程的实际供述支持。

书店第11步唐芮只转述林沅递卡给赵澄，未再把借卡说成自己经历。林f7第10步开放，赵f8第16步开放，唐f9在第14步满足组合前置后开放、第15步实际承认付款借书；唐f10第16步开放、第17步实际说明寄柜。20个回合未出现未拆谎先改口、主体误归或未授权秘密公开。第2步“今晚到货登记和前窗排面我都参与了”沿用profile的相对时间措辞，调查背景为次日，作为P3原句留档，三题绝对时间与修正后的追回日期分别成立。

每题证据、实际口供、秘密开放时刻、18/20句逐句结论及错答枚举见 [医院逐题与逐句证据](task18-quality/final/hospital/question-evidence.json) 和 [书店逐题与逐句证据](task18-quality/final/bookstore/question-evidence.json)，均绑定当前story、design、playthrough与result的原始SHA。真实整局原记录见 [医院18步](task18-quality/actor-replay/hospital/playthrough.json) 与 [书店20步](task18-quality/actor-replay/bookstore/playthrough.json)。医院原审稿误报与38e9199正式复核结果分开记录，原story.yaml及result.json的rawfalse完整保留。

### 医院仅调整质量标记的验收副本

生产四例真实校准、当前策略复核与严格整局验收全部通过后，由原story.yaml字节复制生成tested-story.yaml，仅将单独一行checked:false改为checked:true，其余字节保持。YAML解析后移除该标记差异，所有字段逐项相同，重新运行结构与好玩度检查通过。原设计、剧情、证据、取得条件、口供和结局均对应原指纹。

原story SHA256为 `072617db5a1436dc532afb421a63e75533dc4dd4ed993d9ee8542604fcdb6cfe`，tested-story为 `42f3f81ab769570b0355cea2b91974cd6f9b6504145fa6cc9cf0ed35edf16808`。完整原稿、设计、result、逐句证据、实际试玩与38e9199复核的映射见 [tested-story-mapping.json](task18-quality/final/hospital/tested-story-mapping.json)，副本见 [tested-story.yaml](task18-quality/final/hospital/tested-story.yaml)。书店原稿自动true保持原值，P3相对时间措辞继续公开记录。

## 原始数据与敏感信息扫描

收集脚本按 `diagnostics/` 保存早期批次、OpenAI正式第2至第4批、精修批次及传输诊断，按 `comparisons/deepseek-final/` 保存DeepSeek第3批，按 `final/` 保存分别指定的最终医院和书店。固定对照和各版reviewer原始请求响应独立保留。

JSON、YAML及日志按原字节保存并计算SHA256，日志后缀映射为txt。manifest记录源路径、复制后指纹、选中设计匹配的设计响应和填表请求。原设计响应的null correction若被解析时排除，匹配索引使用同一DesignDraft模型规范化并记录方法，原始响应字节保持完整。已有手填证据先核对原始story/design SHA。同源手填内容继续保留，异源旧表按字节复制归档后由新来源覆盖；新来源尚无证据表时生成明确绑定新SHA的待补占位，避免旧表误映射到新稿。手工内容、旧追踪指纹和归档表分别记录，实际口供与动态复核结论保存在独立证据表。

落盘前扫描环境中所有非空 `*_KEY`，并只读提取用户指定私有txt中的高熵密钥一起扫描。提取值仅用于内存比对。扫描命中即停止收集，原始认证配置由用户私有文件保管。
