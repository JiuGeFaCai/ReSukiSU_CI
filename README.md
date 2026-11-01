# ReSukiSU_CI
这里自动同步 BakaSU（原 ReSukiSU）、KowSU 和 SukiSU-Ultra 的管理器 CI 构建并发布到 Releases，无需 fork。

BakaSU 使用 `17 */5 * * *` 定时同步（UTC 00:17、05:17、10:17、15:17、20:17）。

## KowSU
本仓库同时自动同步 [KowSU](https://github.com/KOWX712/KernelSU)（KernelSU 的 Material 主题分支）Build Manager 的 manager 完整版管理器 APK。
同步任务见 `.github/workflows/kowsu.yml`，Release tag 前缀为 `KowSU_`（BakaSU 为 `ReSukiSU_`），使用 `43 */10 * * *` 定时检查上游构建（UTC 00:43、10:43、20:43）。
cron 按天重置小时范围，因此这两个任务的跨天间隔均为 4 小时。
运行摘要会列出新增发布、补传附件、已同步和上游失败的数量。API 请求失败、成功构建缺少 manager 产物或 APK 不符合预期时，任务会明确失败；已有 Release 缺少 APK 时会尝试补传。

同步脚本的回归测试：`python3 -m unittest discover -s tests -v`（需要 Python 3、Bash、jq 和 unzip）。

## SukiSU-Ultra

自动同步 [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) 的 `main` 分支 Build Manager 中的 `Manager` 完整版管理器 APK，使用 `SukiSU_<run_id>` 标签去重。
工作流见 `.github/workflows/sukisu.yml`，定时计划与 BakaSU 相同：`17 */5 * * *`。
可以手动运行工作流回填最近 10 次构建。发布后会核验附件名称与大小，已有 Release 缺少 APK 时会补传。
