# ReSukiSU_CI
这里是 BakaSU（原 ReSukiSU）的 CI Build 自动发布仓库，仅用于自动拉取 BakaSU 的 CI 构建，无需fork

## KowSU
本仓库同时自动同步 [KowSU](https://github.com/KOWX712/KernelSU)（KernelSU 的 Material 主题分支）Build Manager 的 manager 完整版管理器 APK。
同步任务见 `.github/workflows/kowsu.yml`，Release tag 前缀为 `KowSU_`（BakaSU 为 `ReSukiSU_`），每 3 小时检查一次上游构建。
