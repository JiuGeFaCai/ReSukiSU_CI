# ReSukiSU_CI
这里是 BakaSU（原 ReSukiSU）的 CI Build 自动发布仓库，仅用于自动拉取 BakaSU 的 CI 构建，无需fork

## KowSU
本仓库同时自动同步 [KowSU](https://github.com/KOWX712/KernelSU)（KernelSU 的 Material 主题分支）Build Manager 的 manager 完整版管理器 APK。
同步任务见 `.github/workflows/kowsu.yml`，Release tag 前缀为 `KowSU_`（BakaSU 为 `ReSukiSU_`），每 6 小时检查一次上游构建。
运行摘要会列出新增发布、补传附件、已同步和上游失败的数量。API 请求失败、成功构建缺少 manager 产物或 APK 不符合预期时，任务会明确失败；已有 Release 缺少 APK 时会尝试补传。

同步脚本的回归测试：`python3 -m unittest discover -s tests -v`（需要 Python 3、Bash、jq 和 unzip）。
