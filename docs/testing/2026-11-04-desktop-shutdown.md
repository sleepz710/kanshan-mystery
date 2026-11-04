# 2026-11-04 桌面生成期间关闭验收

基于主分支 `4080` 快照，使用 Windows 11 专业版、Python 3.13.5、pywebview 6.2.1、Edge WebView2，实际调用 `desktop.main.main()` 打开原生桌面窗口及后台 uvicorn。全部数据写入独立系统 TEMP，配置使用假 key。

QA 启动脚本将 `checker.complete_for` 替换成离线异步回复，并将 SDK 客户端构造设置为立即失败。生成仍经过真实对话、任务、设计、填表、程序检查、发布和 lifespan 收尾。第一种场景暂停设计回复，第二种场景暂停真实临时 YAML 写入后的原子替换。两种场景均通过编剧页面提交素材与「快速」，确认前端任务处于生成中后关闭。

## 实际结果

| 场景 | 退出方式 | 关闭用时 | 任务最终状态 | 发布结果 |
|---|---|---|---|---|
| 设计回复等待中 | 原生「应用 → 退出」菜单 | 4.988 秒 | failed，story_id 为空 | 0 份 YAML |
| 临时 YAML 已写入，原子替换等待中 | 原生窗口关闭消息 | 7.095 秒 | done | 1 份完整 YAML |

关闭用时包含 WebView2 窗口和本地服务退出。第二种场景包含 QA 人为延迟的 1.2 秒。该时间用于核对退出行为。

- 设计等待收到 `asyncio.CancelledError`，任务取消完成。待处理任务数归零，端口 14220 释放，`kanshan-backend` 线程结束。
- 保存等待时，窗口关闭后进程继续运行，磁盘只有已写入的 `.tmp`。放行原子替换后任务完成，生成 YAML 可被新引擎列出并开局，临时文件消失。待处理任务数归零，端口 55084 释放，后台线程结束。
- 两轮均记录正常应用 shutdown，入口函数正常返回，SDK 客户端构造次数为 0。
- 保存的案例是固定技术样本「模拟剧场：消失的信」，保留质量警告，本次结果只用于关闭、发布和开局验收。

生产实现无需修改。

## 证据与复跑

本机证据目录为 `%TEMP%/kanshan-desktop-close-20261104-730cef58c8844db8ac17b69b074e2ebe/`。

- `launch_case.py` 在 QA 进程内安装替身后调用真实桌面入口。
- `run_cases.py` 通过真实 WebView2 页面提交素材，执行两种关闭动作并核对结果。
- `results.json` 记录进程、端口、关闭用时与最终状态。
- 每个场景目录保留 `close-before.json`、`close-after.json`、`entry-returned.json` 与桌面日志。设计场景另有取消标记，保存场景另有写入和提交标记。
- `publication-check.json` 记录发布后通过新引擎开局。
- `clean-windows-environment.json` 记录只读环境检查。

桌面入口 SHA256 为 `35A2E4AB0620DABD9BABA6096191EC3EB10F98B88DEC89A6F1B3004EE474BFA9`，生成服务 SHA256 为 `F1511FA7406F3E628E19CD9A409475AD7A8F4F4EBA1ACA164BD56A98E3DA21C9`。

## 干净 Windows 环境

本机未提供 `WindowsSandbox.exe`，`Get-VM` 管理入口不可用。Windows Sandbox 与 Hyper-V 可选组件的 `InstallState` 均为 2，未发现正在运行的 Sandbox、VirtualBox 或 VMware 虚拟机。当前没有可直接使用的干净 Windows 测试环境。

另一台未安装 Python 的 Windows 电脑仍待验收。本轮使用实际桌面源码入口，优化完成后的最终 exe 需要重新打包并做启动复核。
