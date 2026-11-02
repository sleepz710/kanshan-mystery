# 任务 11：比赛提交材料

2026-11-02。提交目标为 11 月 4 日晚，最迟 11 月 5 日；视频按用户确认的约 3 分钟、中文讲解配字幕制作。队名、成员、学校待补。

## 已交付

| 材料 | 文件 | 内容 |
|---|---|---|
| 作品基本信息 | [basic-info.md](basic-info.md) | 一句话介绍、长短版简介、技术方案、创新与价值、待填字段 |
| 作品海报 | [assets/kanshan-poster-v1.png](assets/kanshan-poster-v1.png) | 1024 × 1536 PNG，2.39 MiB，无剧情答案 |
| 海报来源 | [assets/poster-prompt.md](assets/poster-prompt.md) | 内置 imagegen 提示词与校对记录 |
| 视频录制稿 | [video-script.md](video-script.md) | 180 秒分镜、操作顺序、口播和录制要求 |
| 字幕底稿 | [video-subtitles.srt](video-subtitles.srt) | 与口播一致的 UTF-8 SRT；实录剪辑后对齐时间 |
| B 站发布文案 | [bilibili.md](bilibili.md) | 标题、简介、标签、分章时间与链接回填位置 |
| 源码与运行说明 | [仓库 README](../../README.md) | 模拟启动、真实模型配置、测试、部署和当前进度 |

![看山谜案馆海报](assets/kanshan-poster-v1.png)

## 尚未完成

- 正式 MP4 和 B 站视频网址：当前 main 尚未合入游戏前端、生成剧场路由与分享页面，等待任务 04、06、08、13 合入及任务 09 完整试玩后实录。
- 任务 10 的泄密率、生成案件破案率、平均回合数：收到原始报告后再填入视频；当前不填写数值。
- 队名、成员、学校：用户确认暂留待补。
- 公网体验地址与访问口令：由任务 12 交付后回填。口令单独交评委，不写入公开文案。

## 下一位的操作顺序

1. 补齐 `basic-info.md` 的身份字段；确认主分支可完成 SPEC 第 3 节全部演示操作。
2. 按 `video-script.md` 预演并录制真实界面，补入任务 10 的结果；按实录对齐 `video-subtitles.srt`，导出 1920 × 1080、H.264 + AAC 的约 3 分钟 MP4。
3. 使用 `bilibili.md` 发布视频，将审核通过的视频网址回填到该文档和 `basic-info.md`；手机与未登录浏览器各打开一次。
4. 回填公网体验地址；未登录打开 GitHub 仓库确认源码可见，按 README 从空环境复现启动。
5. 在比赛表单粘贴作品信息、源码网址、视频网址，上传 PNG 海报；表单有体验链接栏时填真实公网地址。

## 本轮核验

- 基线：`244423d`，2026-11-02 的 `origin/main`。
- `.venv\Scripts\python.exe -m pytest -q --tb=short --maxfail=1`：272 项通过。
- `backend.studio.check.check_structure` 检查正式 `stories/lost-tuition.yaml`：`ok=true`，问题列表为空。
- 从 YAML 计算：4 个角色、12 条线索、5 句谎话、1 次对质、5 道题、3 个结局。
- PNG 文件头与尺寸已核对，中文文案已目视校对。

测试结果用于记录当前代码状态；视频末尾的数据页使用任务 10 的真实模型评测报告。
