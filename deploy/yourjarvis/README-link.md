# YourJarvis Link

YourJarvis 的 Windows 朋友版发布仓库。

YourJarvis 是 QcShadow 基于 [OpenJarvis 官方项目](https://github.com/open-jarvis/OpenJarvis)
开发的个人定制分支。OpenJarvis 提供基础的本地 AI 框架；YourJarvis 在此基础上增加了中文优先的
Windows 桌面体验、语音、本地记忆、朋友共享、轻量 ZIP 发布包和多渠道更新。这个仓库只发布
YourJarvis 的朋友版成品，不是 OpenJarvis 官方发布仓库。

正式版本请从 [GitHub Releases](https://github.com/QcShadow/YourJarvis-link/releases) 或国内的 [Gitee 仓库](https://gitee.com/QcShadow/your-jarvis-link) 下载。推荐下载 `JARVIS-Friends-Bootstrap-*.zip`：它是无需管理员权限的便携包，不预装大模型；解压后运行 `bootstrap.cmd`，再运行 `setup-jarvis.cmd` 选择本地模型、远程主机或兼容 API。

应用会依次通过 GitHub 和预留的国内镜像检查更新，并在应用内下载新版 ZIP。个人配置、聊天记录、模型和日志保存在应用目录的 `data`、`models`、`logs` 中；覆盖升级时保留这些目录。

本仓库不保存开发源码、API 密钥、个人配置、数据库或模型权重。开发源码保存在私有仓库 `QcShadow/YourJarvis-dev`。

## 首次安装

1. 下载最新 ZIP。
2. 解压到自己的可写目录，例如 `D:\YourJarvis`。
3. 运行 `bootstrap.cmd` 安装运行依赖。
4. 运行 `setup-jarvis.cmd` 完成自检和模型/API 配置。
5. 双击 `JARVIS.exe`。

不要直接在压缩包内运行，也不要安装到 `Program Files`。
