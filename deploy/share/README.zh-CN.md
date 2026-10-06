# JARVIS 朋友版 0.1.3

## 安装与启动

1. 下载并双击 **JARVIS-Setup-0.1.3.exe**，无需解压或运行命令。
2. 选择一个可写的专用安装目录，继续进入中文向导。
3. 默认选择“轻量本地模型”和“先使用文字”。需要语音时，选择中文男声、中文女声或 English。
4. 点击“开始安装”。向导按顺序准备运行环境、桌面组件、模型、语音和配置，并实际测试后端与聊天接口。
5. 完成后点击“启动 JARVIS”。以后使用桌面快捷方式或安装目录中的 **JARVIS.exe**。

首次安装需要联网。文字模式至少预留 4 GB，语音模式建议预留 10 GB。API 模式只下载应用环境，连接时会发送一次短测试请求。

## 下载慢、卡住或失败

默认优先 Gitee，连接失败或连续 30 秒无数据时重试并切换 GitHub。大文件自动分块下载、续传和 SHA-256 校验，无需用户拼接。进度会显示文件名、百分比与已下载大小。

Python、基础依赖、语音依赖、CPU Ollama、默认 Qwen2.5 0.5B、SenseVoice、Kokoro、英文识别资源和 WebView2 离线安装组件均使用发布资源。自定义模型不属于默认镜像范围，需事先在本机 Ollama 安装；API 连接仍需要访问你填写的服务地址。

失败时点“打开日志”，修正问题后重试；已下载内容保留。也可下载发布页的同名资源文件，放到安装目录的 `cache/downloads` 后重试，不要改名。

## 升级、修复和启动失败

先从托盘退出 JARVIS，运行新版安装 EXE，并选择原安装目录。现有 `config.toml`、`credentials.toml`、聊天数据、模型和日志保留。向导默认“保留现有配置并修复环境”。重新配置前会备份旧配置。

启动失败页面提供“重试启动”“修复安装”和“打开日志目录”。详细启动错误保存在 `logs/desktop.log`，后端错误保存在 `logs/gui-server.stderr.log`。

0.1.3 不再分发旧 `bootstrap.cmd` 和独立语音下载脚本；升级会清理这些已被替代的程序文件。旧 `setup-jarvis.cmd` 仅作为兼容入口打开同一图形向导，无需额外运行。

密钥只保存在本机，不进入安装命令参数或日志。第三方组件和模型的来源与许可证见 `THIRD_PARTY_NOTICES.md`。

## 制作者构建

先从明确的 Windows x64 环境生成资源包：`deploy/share/build_resources.py`。该脚本只收集指定的 Python、依赖环境、默认模型和语音文件；用户配置、记忆、聊天、浏览器数据不进入资源包。每个资源块不超过 90 MiB，清单固定全部大小与 SHA-256。

`deploy/yourjarvis/scripts/build-desktop.ps1` 编译启动器、图形向导和原生资源下载器。`deploy/share/build_package.py` 生成仅含程序的 ZIP，`deploy/yourjarvis/scripts/build-setup.ps1` 将该 ZIP 嵌入安装 EXE。打包前需构建前端，并把已验证的 `resources.json` 放入桌面输出目录。
