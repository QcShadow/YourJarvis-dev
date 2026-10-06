# YourJarvis Link

YourJarvis 的 Windows 朋友版发布仓库。

YourJarvis 是 QcShadow 基于 [OpenJarvis 官方项目](https://github.com/open-jarvis/OpenJarvis)
开发的个人定制分支。OpenJarvis 提供基础的本地 AI 框架；YourJarvis 在此基础上增加了中文优先的
Windows 桌面体验、语音、本地记忆、朋友共享、轻量 ZIP 发布包和多渠道更新。这个仓库只发布
YourJarvis 的朋友版成品，不是 OpenJarvis 官方发布仓库。

正式版本请从 [GitHub Releases](https://github.com/QcShadow/YourJarvis-link/releases) 或国内的 [Gitee 发行版](https://gitee.com/QcShadow/your-jarvis-link/releases) 下载。完整解压朋友版 ZIP 后双击 **`JARVIS-Install.exe`**，按中文图形向导选择安装位置、模型/API 和语音，自动完成安装与自检。

应用会依次通过 GitHub 和预留的国内镜像检查更新，并在应用内下载新版 ZIP。个人配置、聊天记录、模型和日志保存在应用目录的 `data`、`models`、`logs` 中；覆盖升级时保留这些目录。

本仓库不保存开发源码、API 密钥、个人配置、数据库或模型权重。开发源码保存在私有仓库 `QcShadow/YourJarvis-dev`。

## 首次安装

1. 下载最新 ZIP。
2. 解压到自己的可写目录，例如 `D:\YourJarvis`。
3. 双击 `JARVIS-Install.exe`，按窗口顺序完成安装。
4. 不确定时保持轻量本地模型和文字模式，首次安装需要联网。
5. 完成后使用桌面快捷方式或 `JARVIS.exe`。失败时在窗口中查看原因、打开日志并重试。

从 0.1.1 升级：退出应用并覆盖程序文件，保留配置、密钥、data、models 和 logs。向导默认保留现有配置并修复环境。bootstrap.cmd 和 setup-jarvis.cmd 都会进入同一向导，无需分别运行。

不要直接在压缩包内运行，也不要安装到 `Program Files`。
