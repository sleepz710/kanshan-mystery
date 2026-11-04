# 任务20汤面null资源同步验收

## 定位

本分支从最新 `origin/main` 的 `16a13da`创建，分支为 `task/20-intro-null-package`。PR #37、#38–#43均已合并，PR #36保留扩展草稿。

用户在本机v2桌面包打开经典案件，汤面标题下出现文字 `null`。交付包的 `frontend/js/game.js`中，`openIntro()`将 `qualityNote()`返回值直接交给原生 `replaceChildren()`。经典案没有 `checked:false`警告，该函数返回null，DOM将它转为文字。

main已在提交 `8f9c097d86fcd73d793b6187db8f26ed978b2be4`修复，将候选节点组成数组后通过 `.filter(Boolean)`过滤。旧v2包漏带这一资源更新。

## 本机资源同步

同步目标为 `D:/阅读周比赛/看山谜案馆-质量收敛交付版-20261104-v2/看山谜案馆/_internal/frontend/js/game.js`。与旧ZIP相比，仅该文件的 `openIntro()`含上述过滤修复。

| 项目 | SHA256 |
|---|---|
| 原game.js | `d3395a275a97309bfddca9bba20c20cef171e61040a9f9c931c51fe5d4ba6fae` |
| 修复后game.js | `585ddba5a00d3998000ea0e1876cc83b4b35aa6bad052c58d2aacd6aba8bf775` |
| 原EXE及资源同步后EXE | `03228edbe1a5816689030fd3a9c20fd9cbdcbd312b029b8dc4ff5ccf82731b39` |

构建来源保留Python构建提交 `2a8a463144ce62d2ffd18bb67418ec7f99ccea1c`，补充 `resource_source_commits`、`hotfixes`记录静态资源来源，`resources`保存实际新指纹。对应说明已纳入SPEC桌面交付。

原ZIP备份在本分支 `.cache/v2-before-intro-null-fix.zip`，SHA256为 `8854a4561555bca867dbfeb908d2557d1ca232186e0f6c252c438772d40eee9f`。原game.js和构建来源备份在 `D:/阅读周比赛/kanshan-task18-complete-20261104/.cache/intro-null-hotfix-20261104`。

## 验收与更新ZIP

最新main `16a13da`在独立工作树中完整pytest为801项通过，用时40.81秒，有一条现有Starlette/httpx兼容提示。

修补后的交付目录EXE使用隔离数据目录和假测试key，通过正常 `POST /api/games`创建经典案，再经实际 `KS.store`及游戏页执行DOM验收。测试端口57381，模型调用0次。

| checked状态 | 首次自动弹窗 | 点击汤面重开 | 刷新后重开 | 质量提示数 |
|---|---|---|---|---:|
| 未设置 | null/undefined文本节点0 | 0 | 0 | 0 |
| true | null/undefined文本节点0 | 0 | 0 | 0 |
| false | null/undefined文本节点0 | 0 | 0 | 1 |

九个场景均保留正确标题和汤面正文。原始结果见 `task20-intro-null/dom-qa.json`。

同名 `D:/阅读周比赛/看山谜案馆-质量收敛交付版-20261104-v2.zip`已按修补后的目录重新生成。ZIP共2,580个文件、46,998,762字节，SHA256为 `9cb3a41d78bc0b0b902792afc6359d5e5b9ac267a2e7937fa13cc42b7b1e5032`。

ZIP CRC、全部成员与本机目录逐文件字节核对通过。相对旧ZIP的文件清单完全一致，变化为game.js和构建来源.json，game.js与main源码逐字节一致。对应记录见 `task20-intro-null/package.json`。

## 使用

本机测试使用上述v2目录中的EXE。关闭已有窗口后重新打开，再从经典案件进入汤面。

分发使用同名的 `看山谜案馆-质量收敛交付版-20261104-v2.zip`，解压后保留完整目录。
