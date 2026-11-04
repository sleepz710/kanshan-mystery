# 2026-11-04 优化版桌面打包验收

冻结源码来自 `D:/阅读周比赛/kanshan-quality-opt-20261104/`，复制到独立目录 `D:/阅读周比赛/kanshan-desktop-optimized-20261104/` 后构建。复制范围使用白名单，包含后端、桌面入口、现有前端、正式剧本及构建说明。源目录的 `.env`、`.cache` 和运行数据均未复制。

任务 21 保持暂停，本次仍使用现有案件目录首页。

## 成品

- 完整目录为 `D:/阅读周比赛/kanshan-desktop-optimized-20261104/dist/final/看山谜案馆/`。
- 主程序为同目录的 `看山谜案馆.exe`。分发时保留整个目录及 `_internal` 依赖。
- EXE SHA256 为 `cda1bee699f1db0c0e0260a71d7530d3956906ee471c9c2fb9885039e0d1408f`。
- 成品包含 2574 个文件，共 96038894 字节，检查未包含 `.env` 或 `.cache`。

构建使用 `D:/CodexData/venvs/kanshan-desktop-20261104/Scripts/python.exe`，Python 3.13.5、PyInstaller 6.22.3、pywebview 6.2.1，执行仓库的 `desktop/build.ps1`。中间构建文件位于系统 TEMP。

## 实机验收

Windows 11、Edge WebView2 环境，实际启动本次成品。独立 `KANSHAN_DATA_DIR` 位于 `%TEMP%/kanshan-desktop-optimized-qa-20261104-6sny0vz2/`。进程 PATH 仅保留 Windows 系统目录，配置使用假 key，远程模型 API 调用为 0。

第一次启动 PID 12700、端口 3540，第二次 PID 10440、端口 27523。

- 设置页通过界面保存模型配置后进入首页，`shelves` 和 `resume` 区域存在。
- 原生「应用」菜单中的模型设置、返回首页、退出均实际点选通过。
- 设置接口仅返回密钥掩码。OpenAI 省略明确模型名时返回 422。
- 使用旧真实生成样本「雪夜账本疑云」开局，返回 201，并在游戏页保留 `checked:false`。
- 关闭后随机端口变化，同一个 game_id `4021ce9f6bee43f39d21bfd6aaa13a53` 的前端记录恢复。对该 game_id 提交空推理返回引擎 422，确认后端同局恢复。
- localStorage 哨兵、1 条编剧技术记录、模型配置与该生成案件目录在第二次启动后保留。
- 两次均正常退出，桌面日志记录应用 lifespan 收尾，进程和监听释放。

旧案例用于开局与持久化回归，保留原质量警告。本轮未重新生成案件或计入生成质量统计。生成期间关闭与原子发布边界的源码实机验收见此前的 `2026-11-04-desktop-shutdown.md` 记录。

## 包内代码核对

直接读取本次 EXE 的 PyInstaller CArchive 和 PYZ。下列八个模块与冻结源码重新编译的 code object 比较通过，比较时仅归一化 `co_filename`。后端和桌面源码的 SHA256 同时与原始冻结目录核对。最终生成服务包含完整真相结局要求全题正确、审稿核查结局条件的最后修订。另有 33 个前端、剧本、设置页资源与源码逐字节核对通过。

| 文件 | SHA256 |
|---|---|
| backend/studio/service.py | `a27eb14ac7d90bc97961273599424e4ef4f3be6bb9e48c94f1444756465b97ed` |
| backend/studio/check.py | `09f89612caefe78d373f96941a7358020ae567aa299a76e65e7f9adc8ead92bf` |
| backend/app.py | `b28b20ba39f946570f0340a37324e6a53d46cacf52a6becdcfbd05248a87c579` |
| backend/engine.py | `e45101b964c13f8b4b51946ce3947a7744caa99134d67dac8c1d395ed9a8e5ab` |
| backend/llm.py | `8590b2359b9b5c94405aa6ccbaaf5e0efab9bfa4be57b96503615fff7221c6d6` |
| desktop/runtime.py | `0736702d9d3c93cc76b2603a7959690526cc0ee646aeaedaf1408b34ccdb7d30` |
| desktop/settings.py | `8a05dca887032c12f0947b5318f21e00a5c5eae8eabbaac5a71a1e43e8411e7f` |
| desktop/main.py | `35a2e4ab0620dabd9baba6096191ec3eb10f98b88dec89a6f1b3004ee474bfa9` |

## 运行证据

本机证据目录为 `%TEMP%/kanshan-desktop-optimized-qa-20261104-6sny0vz2/`。

- `verify_exe.py` 执行两次启动、原生菜单、开局和恢复检查。
- `final-exe-result.json` 记录两次进程、端口与通过项。
- `verify_package.py` 校验 EXE 内嵌代码和冻结源码。
- `package-result.json` 记录成品散列、大小及包内模块比较。
- `source-hashes.json` 记录复制源码散列，桌面日志位于 `logs/desktop.log`。

## 待验收

另一台未安装 Python 的 Windows 电脑仍待验收。本次成品检查在本机缩减 PATH 的环境完成。
