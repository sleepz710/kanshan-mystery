# 任务20桌面质量收敛验收

## 分支与源码

任务20从 `bc4d9ef` 新建独立分支 `task/20-quality-package`。用户先合并本轮任务18，再合并本轮任务20。PR #38、#39、#40已合并，任务21继续暂停，PR #36保持草稿。

最终构建使用本机集成提交 `35ae0e105be1ee1689f5381a951179a42f0d061b`，由任务18运行时 `022f9f46e597adcd9baa0a06ff379562abd5b7e8` 加任务20 `a08c5f2a5f89fcbe68303d63f14d3a77e4846c12` 的桌面入口、模型设置与对应回归构成。任务20 PR保留独立修复与证据。

用户本轮追加OpenAI对照后，真实验收使用 `gpt-5.4-2026-03-05` 同模型，演员 `reasoning_effort=none`，编剧 `high`。快速600秒、精修900秒，OpenAI编剧单次540秒。耗时作为记录，质量结论按检查与实际剧情保留。

## 定位与修复

- 首次启动的数据目录在创建前解析为C盘APPDATA虚拟路径，创建后解析到E盘Codex MSIX物理目录。使用前者做同目录原子改名时，三种后缀组合均返回WinError17。入口改为先创建目录再解析实际路径，设置与存档使用该物理目录。
- 桌面连接测试的直接SDK请求原用 `max_tokens=8`，GPT-5.4需要兼容参数。设置测试对支持的两个GPT-5.4名称使用 `max_completion_tokens=8` 与 `reasoning_effort=none`。
- 新工作树下的隔离QA目录缺文件改名权限，独立 `.tmp` 改名也返回WinError5。本机生成验收使用TEMP隔离数据根，默认路径另用APPDATA隔离子根验收。子进程环境变量指定隔离路径。

默认路径修复后，最终EXE在未设置 `KANSHAN_DATA_DIR` 的子进程中，以隔离APPDATA子根首次启动，真实页面完成首次设置、三个原生菜单、对局与编剧记录跨随机端口恢复。实际虚拟与物理路径保存在 [default-appdata.json](task20-quality/default-appdata.json)，原始失败诊断保存在 [appdata-before-fix.json](task20-quality/appdata-before-fix.json)。

## 自动测试与产物一致性

- 任务20独立分支完整646项通过，用时24.87秒。
- 最终集成源码完整703项通过，用时18.94秒。
- 两次完整测试均有一条现有Starlette/httpx兼容提示。
- PyInstaller归档内18个项目模块的code object与源码重新编译结果相同，前端、正式案件、设置UI共33个资源逐字节相同。
- ZIP CRC通过，交付目录与构建目录逐文件相同，扫描包含DeepSeek与OpenAI私有密钥的内存值，并排除 `.env`、用户设置及存档文件。

## 本机实际程序

子进程PATH仅保留Windows和System32，本机安装有Python。实际EXE采用独立数据目录，模型配置只进入该目录，记录中保留掩码及检查结果。

三份演示案使用任务19人工修订稿，从最终交付目录内EXE逐案开局后关闭，再次启动恢复三个原game_id及质量标记。端口19088→4917，SDK调用0。

| 案件 | 样本id | 开局 | 重启恢复 | checked |
|---|---|---|---|---|
| 汐潮馆的第七位住客 | demo-hotel-revised | 通过 | 通过 | true |
| 潮汐第七人 | demo-tide-revised | 通过 | 通过 | true |
| 末班车的干伞 | demo-bus-revised | 通过 | 通过 | true |

演示案记录见 [exe-samples.json](task20-quality/exe-samples.json)。原稿、修订稿、指纹与真实完整试玩继续按任务19报告映射。

### 真实生成与关闭

本节待本轮已启动的最终EXE医院生成及生成中关闭完成后补齐。

### 前序非流式诊断

OpenAI旧非流式候选EXE完成真实连接和招牌案两回合。医院生成三轮设计均在180秒无正文超时，任务failed，观察到任务后用时537.32秒，未发布案件。该记录属于模型调用完成失败，剧情质量尚无输出可判。诊断保留于 [exe-openai-nonstream-failure.json](task20-quality/exe-openai-nonstream-failure.json)。

任务18随后用同一后台请求取回完整设计，运行时改为Responses后台轮询并在取消时向提供方取消已获ID的请求。最终包采用此修复。

首版后台轮询候选EXE的医院设计运行159.34秒，已成功轮询同一response多次。随后一次GET出现APIConnectionError，现有清理逻辑取消该response，提供方 `/cancel` 返回200，任务failed并正常退出。该批没有选中稿，记录见 [exe-openai-background-poll-failure.json](task20-quality/exe-openai-background-poll-failure.json)。任务18正在补同ID的可恢复GET重试，后续最终包采用修复后的源码。

## 交付

最终ZIP位于 `D:/阅读周比赛/看山谜案馆-OpenAI后台设计验收版-20261104.zip`，47,005,870字节，SHA256为 `e611cbede65a1478059f78d27f1b48d54e7f719ee2436063f17334fc746b144e`。

完整目录位于 `D:/阅读周比赛/看山谜案馆-OpenAI后台设计验收版-20261104/`。EXE的SHA256为 `4959017eb3143ade70149d2a06e01850a50b85a72a8e2ec261a9207a8d23cd8c`。目录包含2,580个文件、96,096,473字节，附三份人工修订演示案、manifest与验收说明。构建来源、源码及资源指纹见 [build-provenance.json](task20-quality/build-provenance.json) 和包内 `看山谜案馆/构建来源.json`。

## 另一台未安装Python的Windows电脑

1. 将本节最终ZIP复制到Windows 10/11 x64电脑，全部解压，保留EXE旁的 `_internal`，双击 `看山谜案馆.exe`。环境需有Edge WebView2 Runtime。
2. 首次选OpenAI，演员和编剧均填 `gpt-5.4-2026-03-05`，填写自己的API key，测试连接并保存。
3. 打开「一笔消失的学费」问两回合，确认对白、回合数及线索。
4. 新建生成剧场，输入“我想玩恐怖一点的，医院题材”，依次回复“全新”和“快速”，记录完整用时、质量提示并开局。
5. 关闭重开，确认设置、两回合记录、生成案件及原game_id可继续。
6. 新建另一生成，进入设计后关闭，重开确认既有记录完整、目录没有半份新稿。

回传Windows版本、是否安装Python、连接结果、生成用时与质量提示，以及重启后的记录截图。日志保留在 `%APPDATA%/KanshanMystery/logs/desktop.log`。

## 已知问题

- 另一台未安装Python的Windows电脑完整流程待用户执行。
- 当前最终EXE的真实生成与生成中关闭验收正在本机完成，结果待补齐。
