# 评测工具

两个命令默认运行模拟管线，报告标记 `mode: mock`。加 `--live` 才调用真实模型并产生费用。模拟结果用于验证调用、统计和导出流程，视频里的模型能力数据应来自 `mode: live` 的报告。

## 泄密率

```powershell
python -m eval.leak_test --story-id lost-tuition --questions-per-character 1
```

默认每个角色 30 个问题。每个角色从同一个初始状态出发，每道问题分别在核查关闭、开启时测试，问题和初始上下文相同，不把上一道问题加入历史。

`--concurrency` 控制同时执行的评测问题数，默认 4，可设为 1 到 8。每个问题内部的角色回复、核查、重写和独立评判依次执行；不同问题并行。报告仍按原来的剧本、角色、问题及关闭/开启核查顺序输出，完成先后不会改变记录顺序。

真实小样本验证：

```powershell
python -m eval.leak_test --live --story-id lost-tuition --questions-per-character 1 --concurrency 4 --output-dir data/eval/live-smoke
```

- 关闭核查：角色回复后交给独立评测提示词判断泄密。
- 开启核查：角色回复、运行时核查、必要时重写一次；再次被拒绝记 `blocked`，不展示回复，也不记为一次干净回答。
- 独立评测使用另一个提示词调用演员模型，结合允许事实、受禁事实、剧本谎话和公开证据判断。它不会把运行时核查结果直接当作最终评分。
- `completed`：已经取得最终可见回复，且独立评测成功。
- `leaked / completed`：已评测可见回复中的泄密比例。
- `intercepted / attempted`：核查至少拒绝过一次候选回复的比例。
- `blocked / attempted`、`failed / attempted`：阻止显示与调用/评测失败的比例。
- 分母为 0 时报告 `null`。失败和阻止显示的记录不会被补成“零泄密”。

JSON 保留问题、最终可见回复、各次候选回复、核查结果、重写、受禁事实编号和错误类型，便于人工复核。模拟评分只做完整事实文本匹配，不代表语义核查效果。

## AI 完整试玩

```powershell
python -m eval.play_test --runs 1 --max-turns 40
```

默认选择 `data/stories/` 中已有的生成案件。没有样本会明确提示并退出，不创建剧本。可以用 `--story-id lost-tuition` 指定现有招牌案件作接口验证。

```powershell
python -m eval.play_test --live --story-id lost-tuition --runs 1 --max-turns 10 --output-dir data/eval/live-smoke
```

玩家仅看到公开开场、角色介绍、选项、已获线索、公开事件与自己的历史。动作通过引擎执行，不能直接改信任度或取得隐藏线索。重试结局允许继续调查；连续 3 次非法动作会停止，所有动作尝试都受 `--max-turns` 限制。

评测的回合数包括问话、出示、汤主提问、提交和非法动作尝试；引擎评级使用的计数只包含成功的问话与出示，两者口径不同。`history` 保存成功动作，`attempts` 同时保存失败动作及安全错误代码；未经校验的提案只保留通用标志。

- `success`：公开结局的 `id` 为 `truth`，或全题正确（`score == total` 且 `total > 0`）。
- `failed`：进入不可重试的非成功结局，或达到回合上限时仍只有可重试结局。
- `timeout`：达到回合上限但未提交过推理，或模型响应超时。
- `error`：模型/接口错误、返回数据错误，或非法动作达到上限。
- 破案率为 `success / runs`，错误和超时保留在分母中。
- 平均回合数只对成功对局计算；没有成功时为 `null`。

模拟玩家轮流问话、出示已获证据，最后根据公开判分尝试选项。报告标记 `deterministic_public_strategy`，不把这种策略的成功率称作模型表现。

## 样本与输出

`--stories-dir` 指定只读固定剧本目录，`--generated-stories-dir` 指定只读生成剧本目录。使用 `tests/fixtures/v1` 时只是冻结旧样本的技术验证，报告会保留实际来源目录和 `source`，不能当作第二版或生成案件的结果。

默认输出到 `data/eval/`，包含 `leak-test.json` / `.csv` 和 `play-test.json` / `.csv`。CSV 是汇总数据，可用于制作视频图表。重复运行同一种命令会覆盖同名报告，保留历史时使用不同的 `--output-dir`。

退出码：0 表示管线完成，1 表示出现调用或样本错误，2 表示没有找到所选样本。正常的阻止显示、未破案或达到回合上限仍会导出完整记录。

2026-11-02 的招牌案件实测汇总、视频用表与已知问题见 [结果说明](results/2026-11-02/README.md)。
