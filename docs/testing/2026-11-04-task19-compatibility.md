# 任务19演示案兼容复核

本轮分支为 `task/19-demo-compatibility`，从 `bc4d9ef2c4cfa8cfd90ec80f6a7804777bca6db1` 的最新 `origin/main` 建立。PR #39 已合并，后续复核使用本轮独立 PR。任务21继续暂停，PR #36 保持扩展草稿。

## 样本与原验收

复核三份人工修订演示案《汐潮馆的第七位住客》《潮汐第七人》《末班车的干伞》。三个原始生成稿和三个修订稿的 SHA256 均与 `task19-demo/manifest.json` 一致。原稿保留 `checked:false`，人工修订稿按已完成验收保留 `checked:true`。

逐题证据与实际口供、真实双盲、完整真实角色路线，继续对应 [原验收报告](2026-11-04-task19-demo-acceptance.md) 与 [样本映射](task19-demo/manifest.json)。三份演示案的兼容缺陷为0项。

将当前三个修订稿的 `checked:true` 回置为 `checked:false` 后，字节 SHA256 均精确等于旧真实记录中的 `tested_story_sha256`。实际试玩稿与交付稿的质量元数据映射验证通过。

## 回放方法

[replay.py](task19-compat/replay.py) 接收待复核源码目录，在临时数据目录创建应用，通过正常 ASGI HTTP 路由列举、开局、问话、出示、拆谎、对质和结案。每步演员对白、已交材料、对质对白来自原有真实验收记录，核查使用通过响应替身。原记录只保存公开回合结果，演员的信任增量按已有规则复原，公交第9步保留材料保底对应的信任处理。

每步比较完整公开响应，并比较开局事实权限、最终事实权限、已取证据、拆谎与事件集合。结案使用原公开调查记录答题模型的答案，通过实际路由提交一题错和全错，再穷举各题全部选项组合。两个模型客户端入口均设为失败哨兵，实际模型调用为0次。角色语义与双盲质量依据来自原真实验收记录。

在仓库根目录执行以下命令，`<待复核源码>` 替换成实际目录。

```powershell
& D:/CodexData/venvs/kanshan-desktop-20261104/Scripts/python.exe `
  docs/testing/task19-compat/replay.py `
  --source-root '<待复核源码>' `
  --output docs/testing/task19-compat/compatibility.json
```

## 主线基线结果

基线源码为 `bc4d9ef2c4cfa8cfd90ec80f6a7804777bca6db1`，逐步结果及六个运行模块的源码指纹见 [baseline.json](task19-compat/baseline.json)。

| 演示案 | 完整回放 | 线索 | 拆谎 | 事件 | 结案 | 错答完整真相 |
|---|---|---|---|---|---|---|
| 汐潮馆的第七位住客 | 13步一致 | 10/10 | 3/3 | 5/5 | 4/4 | 0/256组合 |
| 潮汐第七人 | 17步一致 | 10/10 | 3/3 | 2/2 | 4/4 | 0/256组合 |
| 末班车的干伞 | 16步一致 | 10/10 | 4/4 | 2/2 | 4/4 | 0/256组合 |

三案均能正常列举和开局，每步公开结果与原真实记录一致。每案完整真相仅1种全对组合命中，实际一题错与全错提交均进入 `retry:true` 的结局。

独立任务19分支执行完整 `python -m pytest -q`，642项通过，31.30秒，保留1项现有 Starlette/httpx 弃用提示。

## 任务18收敛源码复核

任务18收敛源码固定为 `b02f0c5515355f0f7e87f1b6114ba6aa70a0e735`，运行模块无未提交修改。相同脚本的最终结果见 [compatibility.json](task19-compat/compatibility.json)，包含六个运行模块的 SHA256。生成流程与模型请求涉及的 `backend/studio/service.py`、`backend/studio/check.py` 和 `backend/llm.py` 与主线基线有改动。

独立任务19分支最终全量pytest复跑为642项通过，29.98秒，保留同一项现有弃用提示。

三案全部兼容，46步完整公开结果、开局及最终事实权限、线索/拆谎/事件集合、正确结案及错答隔离，与主线基线逐项一致。逐题证据和实际口供继续对应相同的原验收文件指纹。

## 档位问句按钮修复

任务18将档位问句调整为“快速还是精修？精修会比较两份设计，并增加修订轮次。实际耗时取决于素材和模型。”。原前端仅匹配带“快速（约3分钟）还是精修”的旧问句，新问句会显示普通改编策略按钮。本轮修改实际renderSuggest中的一行匹配表达式，覆盖新旧问句。

离线Node脚本从实际前端源码提取renderSuggest执行，10项断言通过。覆盖新旧问句、JSON历史恢复、快速/精修按钮的发送值、普通改编策略对话、保留的share对话，以及用户末条消息、busy和生成中状态。`node --check frontend/studio/studio.js`通过。脚本与结果见 [quality-suggestions.cjs](task19-compat/quality-suggestions.cjs) 和 [quality-suggestions.json](task19-compat/quality-suggestions.json)。本次按钮回归使用轻量DOM与发送替身，模型调用0次。

## 待完成

- 队员主观体验和视频录制继续在交付环境执行。
