# 任务20桌面质量收敛验收

## 分支与源码

任务20从 `bc4d9ef` 新建独立分支 `task/20-quality-package`。用户先合并本轮任务18，再合并本轮任务20。PR #38、#39、#40已合并，任务21继续暂停，PR #36保持草稿。

最终构建使用本机集成提交 `848c471f4f2b35b2ac6dad3d6cef33b0d4c630cb`，由任务18运行时 `b02f0c5515355f0f7e87f1b6114ba6aa70a0e735`、任务19前端 `486ca74ba0a4f8da9671347b8fef39b6e34b207f` 与任务20 `a08c5f2a5f89fcbe68303d63f14d3a77e4846c12` 的桌面入口、模型设置和对应回归构成。任务20 PR保留独立修复与证据。

用户本轮追加OpenAI对照后，真实验收使用 `gpt-5.4-2026-03-05` 同模型，演员 `reasoning_effort=none`，编剧 `high`。按真实完整轮次调整后的OpenAI快速预算1200秒、精修1800秒，编剧单次540秒，DeepSeek快速600秒、精修900秒。耗时作为记录，质量结论按检查与实际剧情保留。

## 定位与修复

- 首次启动的数据目录在创建前解析为C盘APPDATA虚拟路径，创建后解析到E盘Codex MSIX物理目录。使用前者做同目录原子改名时，三种后缀组合均返回WinError17。入口改为先创建目录再解析实际路径，设置与存档使用该物理目录。
- 桌面连接测试的直接SDK请求原用 `max_tokens=8`，GPT-5.4需要兼容参数。设置测试对支持的两个GPT-5.4名称使用 `max_completion_tokens=8` 与 `reasoning_effort=none`。
- 新工作树下的隔离QA目录缺文件改名权限，独立 `.tmp` 改名也返回WinError5。本机生成验收使用TEMP隔离数据根，默认路径另用APPDATA隔离子根验收。子进程环境变量指定隔离路径。

默认路径修复后，最终EXE在未设置 `KANSHAN_DATA_DIR` 的子进程中，以隔离APPDATA子根首次启动，真实页面完成首次设置、三个原生菜单、对局与编剧记录跨随机端口恢复。实际虚拟与物理路径保存在 [default-appdata.json](task20-quality/default-appdata.json)，原始失败诊断保存在 [appdata-before-fix.json](task20-quality/appdata-before-fix.json)。

## 自动测试与产物一致性

- 任务20独立分支完整646项通过，用时22.01秒。
- 最终集成源码完整743项通过，用时32.80秒。
- 两次完整测试均有一条现有Starlette/httpx兼容提示。
- PyInstaller归档内18个项目模块的code object与源码重新编译结果相同，前端、正式案件、设置UI共33个资源逐字节相同。
- ZIP CRC通过，交付目录与构建目录逐文件相同，扫描包含DeepSeek与OpenAI私有密钥的内存值，并排除 `.env`、用户设置及存档文件。

## 本机实际程序

子进程PATH仅保留Windows和System32，本机安装有Python。实际EXE采用独立数据目录，模型配置只进入该目录，记录中保留掩码及检查结果。

三份演示案使用任务19人工修订稿，从最终交付目录内EXE逐案开局后关闭，再次启动恢复三个原game_id及质量标记。端口37913→19903，SDK调用0。

| 案件 | 样本id | 开局 | 重启恢复 | checked |
|---|---|---|---|---|
| 汐潮馆的第七位住客 | demo-hotel-revised | 通过 | 通过 | true |
| 潮汐第七人 | demo-tide-revised | 通过 | 通过 | true |
| 末班车的干伞 | demo-bus-revised | 通过 | 通过 | true |

演示案记录见 [exe-samples.json](task20-quality/exe-samples.json)。原稿、修订稿、指纹与真实完整试玩继续按任务19报告映射。

### 真实生成与关闭

最终EXE在实际设置页选OpenAI，演员与编剧填同一GPT-5.4快照，连接成功。招牌案两回合取得两条线索，关闭后在新随机端口恢复同一game_id、两回合及两条线索。原生模型设置、返回首页和退出均通过，关闭后进程退出并释放端口。

最终新生成通过实际编剧页输入“我想玩恐怖一点的，医院题材”，依次确认“全新”和“快速”。任务 `fe8e733ed5034265b17661678e61d5d6` 完成两轮设计并保存「307病房的消音键」。从浏览器观察到任务后计时773.33秒，14次模型步骤合计777.65秒。第2轮首次填表180秒超时，在同设计剩余填表次数内恢复。实际输出 `checked:false`，界面显示检查未全部通过。

| 轮次 | 步骤 | 各次耗时 |
|---|---|---|
| 1 | 设计 | 211.79秒 |
| 1 | 填表 | 37.29、17.82、33.42秒 |
| 1 | 设计审稿 | 9.17秒 |
| 1 | 汤面盲答、全部线索盲答 | 8.87、3.54秒 |
| 2 | 设计修订 | 131.41秒 |
| 2 | 填表 | 180.01秒超时、42.36、10.93秒 |
| 2 | 设计审稿 | 47.38秒 |
| 2 | 汤面盲答、全部线索盲答 | 40.16、3.50秒 |

生成案开局后，唐晟、林若薇分别完成一次真实角色问话，用时63.60、24.47秒，交出死亡记录单和夜班交接本。两名角色的实际对白见 [exe-live.json](task20-quality/exe-live.json)。关闭后端再启动，在端口34827恢复原game_id、两回合、两条线索、模型配置和 `checked:false`。

另外新建一次医院生成，确认正在设计且提供方已返回response ID后关闭窗口。进程10.19秒退出并释放端口，提供方同ID的 `/cancel` 返回HTTP200。重启后既有生成案及对局完整，发布目录没有半稿。实际取消任务ID为 `725ae64ac154473e89469c5d2ff969d6`，response ID与HTTP状态保存在同一记录。

QA驱动直接开局早于前端完成任务卡片的终态轮询，重启后该卡片被标为失效，生成案目录与两回合对局均已恢复。驱动已增加等待卡片done后再开局，补充验证按以下证据分开记录。

| 路径 | 证据类型 | 结果 |
|---|---|---|
| 生成后通过前端游戏API开局并问两名角色 | 实际计费结果 | 两问、两线索及原局重启恢复通过 |
| 最终EXE首页目录点击「307病房的消音键」 | 实际已生成案件，SDK调用0 | 正常新局、0回合、checked:false及警告通过 |
| 已完成真实响应与故事构成fixture，点击生成卡片后重启 | 离线回放，SDK调用0 | 开局与done卡片重启恢复通过 |

首页目录记录见 [exe-directory-open.json](task20-quality/exe-directory-open.json)，回放记录见 [card-replay.json](task20-quality/card-replay.json)。回放补充了已完成状态的卡片行为，本轮计费生成到原卡片点击的连续路径仍待复核。

### 前序非流式诊断

OpenAI旧非流式候选EXE完成真实连接和招牌案两回合。医院生成三轮设计均在180秒无正文超时，任务failed，观察到任务后用时537.32秒，未发布案件。该记录属于模型调用完成失败，剧情质量尚无输出可判。诊断保留于 [exe-openai-nonstream-failure.json](task20-quality/exe-openai-nonstream-failure.json)。

任务18随后用同一后台请求取回完整设计，运行时改为Responses后台轮询并在取消时向提供方取消已获ID的请求。最终包采用此修复。

首版后台轮询候选EXE的医院设计运行159.34秒，同一response成功轮询64次。随后一次GET出现APIConnectionError，清理逻辑取消该response，提供方 `/cancel` 返回200，任务failed并正常退出。该批没有选中稿，记录见 [exe-openai-background-poll-failure.json](task20-quality/exe-openai-background-poll-failure.json)。任务18已补同ID的可恢复GET重试，最终包采用修复后的源码。

前一冻结候选 `f93a36b` 的任务在后台create阶段2.91秒APIConnectionError，尚未获得response ID，停止该批付费。QA原先只等待running状态，未立即捕捉已经failed的任务，已由持久化和服务日志补齐记录，并修复驱动以接收全部终态。原始结果见 [exe-openai-create-failure.json](task20-quality/exe-openai-create-failure.json)。此后按恢复的真实请求证据，在新交付包另开独立任务完成上述验收。

## 交付

最终ZIP位于 `D:/阅读周比赛/看山谜案馆-质量收敛交付版-20261104.zip`，46,978,968字节，SHA256为 `c7c2c2650bfe5b26f3e2eced1b7029551c0f161d99df62ca6e7d4c6d88d8cdef`。

完整目录位于 `D:/阅读周比赛/看山谜案馆-质量收敛交付版-20261104/`。EXE的SHA256为 `e0caf041111ad9469d94ad4a399b02cfac66546427ebe5a9e61602ab33c1604f`。目录包含2,580个文件、96,099,301字节，附三份人工修订演示案、manifest与验收说明。构建来源、源码及资源指纹见 [build-provenance.json](task20-quality/build-provenance.json) 和包内 `看山谜案馆/构建来源.json`。

## 另一台未安装Python的Windows电脑

1. 将本节最终ZIP复制到Windows 10/11 x64电脑，全部解压，保留EXE旁的 `_internal`，双击 `看山谜案馆.exe`。环境需有Edge WebView2 Runtime。
2. 首次选OpenAI，演员和编剧均填 `gpt-5.4-2026-03-05`，填写自己的API key，测试连接并保存。
3. 打开「一笔消失的学费」问两回合，确认对白、回合数及线索。
4. 新建生成剧场，输入“我想玩恐怖一点的，医院题材”，依次回复“全新”和“快速”，记录完整用时、质量提示，点击生成卡片的「开始调查」。
5. 关闭重开，确认设置、两回合记录、生成案件及原game_id可继续，编剧记录中的原卡片仍显示已生成。
6. 新建另一生成，进入设计后关闭，重开确认既有记录完整、目录没有半份新稿。

回传Windows版本、是否安装Python、连接结果、生成用时与质量提示，以及重启后的记录截图。日志保留在 `%APPDATA%/KanshanMystery/logs/desktop.log`。

## 已知问题

- 另一台未安装Python的Windows电脑完整流程待用户执行。
- 最终EXE新增医院案保持checked:false，结构检查通过，好玩度仍有周启明持有5/9条线索超过一半的问题，见 [exe-hospital-local-checks.json](task20-quality/exe-hospital-local-checks.json)。
- QA提前离开编剧页造成任务卡片终态未保存，计费生成到原卡片点击的连续路径仍待复核，首页目录与离线已完成卡片已通过补验。
