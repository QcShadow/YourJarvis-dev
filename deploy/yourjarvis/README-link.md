# YourJarvis Link

YourJarvis 的 Windows 朋友版发布仓库。

YourJarvis 是 QcShadow 基于 [OpenJarvis 官方项目](https://github.com/open-jarvis/OpenJarvis)
开发的个人定制分支。OpenJarvis 提供基础的本地 AI 框架；YourJarvis 在此基础上增加了中文优先的
Windows 桌面体验、语音、本地记忆、朋友共享、单 EXE 安装包和多渠道更新。这个仓库只发布
YourJarvis 的朋友版成品，不是 OpenJarvis 官方发布仓库。

正式版本请从 [GitHub Releases](https://github.com/QcShadow/YourJarvis-link/releases) 或国内的 [Gitee 发行版](https://gitee.com/QcShadow/your-jarvis-link/releases) 下载 **JARVIS-Setup-0.1.3.exe**，直接双击，按中文向导完成安装，无需解压或输入命令。

安装和更新优先 Gitee，失败自动切换 GitHub。资源分块下载、断点续传并校验 SHA-256。安装器会从发布地址补齐 Python、应用及语音依赖、CPU Ollama、默认 Qwen2.5 0.5B、SenseVoice、Kokoro、英文识别模型和 WebView2 离线组件。

应用和模型资源放在发行版附件，运行环境及语音资源分别托管于 Gitee 的 `your-jarvis-runtime` 和 `your-jarvis-speech`；安装器自动使用对应地址。开发源码保存在 `QcShadow/YourJarvis-dev`，发布包不包含制作者的密钥、私人配置、聊天、记忆或浏览器数据。

## 首次安装

1. 下载并双击安装 EXE。
2. 选择安装位置，不确定时保持轻量本地模型和文字模式。
3. 点击开始安装，等待运行环境、模型和实际后端启动检查通过。
4. 完成后使用桌面快捷方式或 `JARVIS.exe`。
5. 失败时查看日志、修改方案并重试；启动失败页也提供“修复安装”。

从旧版升级：从托盘退出应用，运行新版安装 EXE，选择原来的安装目录。向导保留现有配置、密钥、data、models 和 logs，并清理旧 bootstrap / 独立语音下载入口。无需另外运行 setup-jarvis.cmd。

建议使用默认安装位置或独立文件夹。
