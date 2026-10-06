# JARVIS 分享版：首次配置与朋友网页

这是可重新生成的 Windows x64 引导包，包含应用代码、网页界面、配置向导和 uv。它不是完全离线的安装器：首次安装 Python 和依赖需要联网；本地语言模型需要 Ollama，原生窗口需要 Microsoft WebView2。包内不复制制作者的配置、API 密钥、私人记忆、聊天记录或浏览器数据。

## 朋友在自己的电脑上使用

1. 完整解压 ZIP 到自己的可写目录，例如 `D:\YourJarvis`。不要直接在压缩包里运行。
2. 双击 **`JARVIS-Install.exe`** 打开中文图形安装向导。
3. 按窗口顺序选择安装目录、模型与语音方案，再点击“开始安装”。不确定时保持“轻量本地模型”和“先使用文字”。本地模型无需 API 密钥；使用 API 时填入服务商提供的地址、模型名称和密钥。
4. 向导自动检查安装包、安装 Python 与依赖、补齐 WebView2 / Ollama、下载所选模型和语音、测试模型连接，最后保存配置和自检。首次安装请保持联网，至少预留 4 GB；语音建议预留 10 GB。API 检查会发送一次很短的测试请求。
5. 完成后点击“启动 JARVIS”，以后直接使用桌面快捷方式或 `JARVIS.exe`。首次双击 `JARVIS.exe` 也会在缺少环境时打开同一个向导。

**遇到失败**：窗口下方会显示原因，可点“打开日志”；检查网络后点“重试安装”，或点“上一步”修改方案。已完成的依赖与模型下载会复用。请先退出已有 JARVIS 再安装或修复。

**从 0.1.1 升级**：退出 JARVIS，将新版 `JARVIS-Share` 内的文件解压覆盖到原目录，保留 `config.toml`、`credentials.toml`、`data`、`models`、`logs`。再打开 `JARVIS-Install.exe`，默认勾选“保留此目录的现有配置，仅修复运行环境”。要重新选择方案可取消该选项；旧配置会先备份。`bootstrap.cmd`、`setup-jarvis.cmd` 都会进入同一个图形向导，无需分别运行。

密钥输入会隐藏，单独保存于本机 `credentials.toml`，不会出现在安装命令参数或安装日志中。

设置页的“模型与首次配置预设”支持轻量模型、已有 Ollama 模型、兼容 API 地址和密钥。保存会备份旧配置，保留人物提示词、语音、个人记忆设置。应用需重新启动后端才能切换：先 `stop-gui.cmd`，再 `start-gui.cmd`。托盘窗口的关闭按钮仅隐藏窗口，不代表后端已重启。

独立 API 方案只展示配置的模型，不探测其他电脑上的模型，也不自动下载本地 LLM。地址可以含 `/v1`，会避免重复拼接；如 `http://localhost:1234/v1`，或服务商提供的兼容地址。模型 ID 必须按服务商或本地服务的实际名称填写。原生 Anthropic / Gemini 协议与 OpenAI 兼容协议不同，这个通用入口要求服务端提供兼容协议。

也可命令行配置：

```powershell
./jarvis.cmd setup presets
./jarvis.cmd setup configure --profile lite --voice zh
./jarvis.cmd setup configure --profile api --base-url http://localhost:1234/v1 --model my-model --voice text
./jarvis.cmd setup configure --profile api --base-url https://your-provider.example/v1 --model your-model --prompt-api-key --voice zh
./jarvis.cmd setup check
```

配置已存在时需显式 `--replace`，向导会先生成带时间戳的备份。这个首次配置命令会重建模型、语音和初始行为配置；已有个人设置可在界面只修改模型连接。自己的 API 环境变量也可通过 `--api-key-env YOUR_KEY_NAME` 指定。移动整个目录后，重新运行配置向导生成当前目录的语音路径。`credentials.toml` 是本机明文密钥文件；Windows 的访问范围取决于目录的 NTFS 账户权限，不是加密保险库。

## 轻量模型与硬件

以下是工程估算，不是最低配置或实时语音保证。操作系统、浏览器、上下文长度和其他程序会改变实际占用；下载体积不等于运行内存。这里优先选择中文可用的小模型，并限制上下文，避免一开始加载大型推理模型。

| 方案 | 默认模型 / 语音 | 建议整机内存 | 显卡 | 适用 |
| --- | --- | --- | --- | --- |
| 极轻量文字 | Qwen2.5 0.5B Q4_K_M，约 398 MB，2048 token 上下文 | 4 GB 可尝试，8 GB 更舒适 | 无需独显，强制 CPU | 中文短对话、确认软件可用；复杂推理和工具执行能力有限 |
| 极轻量中文语音 | 上述 LLM + SenseVoice INT8 + Kokoro 云健 / 晓晓 | 建议 8 GB 起，16 GB 更舒适 | 无需独显 | 中文听写、短句播报；语音模型与 Python / Torch 额外占空间与内存 |
| 更好的中文聊天 | Qwen3 1.7B Q4_K_M，约 1.4 GB，4096 token 上下文 | 建议 8 GB 起，16 GB 更舒适 | CPU 可用；兼容 GPU 可加速 | 更自然的普通聊天，默认关闭模型扩展思考 |
| API / 自建服务 | 用户填写 API 或本地服务 | 取决于浏览器 / 应用与是否启用本地语音 | 客户端可无需显卡 | 计算主要由 API / 自建服务器承担 |
| 朋友只用网页 | 主机统一处理 LLM，朋友浏览器运行聊天页 | 朋友设备只承担浏览器开销 | 朋友无需显卡 | 当前版本为文字聊天 |

默认中文识别使用 SenseVoiceSmall ONNX INT8，默认声音是 Kokoro 的云健或晓晓；英文识别使用 Whisper `small.en` INT8，声音是 George。模型和声音分别设置，不需要选某个大 LLM 才能用中文语音。语音接听默认关闭，由用户主动启用。实验性的跨语言 JARVIS 声线和 Qwen-TTS 大型运行时不在分享包默认预设中。

纯 CPU 样例已在制作者的 AMD 16 核 / 约 32 GB 内存主机上验证：`num_gpu=0`、`num_ctx=2048`，中文自我介绍首次完整请求约 2.3 秒。这只代表该机器的一次冒烟测试，不能推导普通 4 GB 电脑的速度。

官方来源：[Qwen2.5 0.5B](https://ollama.com/library/qwen2.5:0.5b)、[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)、[Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b)、[Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)、[SenseVoice ONNX](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17)。

## 用自己的主机给几位朋友提供网页

可以实现。已提供独立的 `friends` 网关，网页、聊天 API 和身份验证运行在独立进程 / 端口，直接调用主机模型，不挂载私人助手的记忆、文件、桌面、工具、审批或配置接口。朋友只能发文本历史，不能更改模型、系统提示或工具权限。会话只留在当前网页内存，服务不持久保存朋友的聊天；主机作为处理方仍能接触推理数据。

默认一次处理 1 条推理，最多 4 人等待；同一令牌一次只能有 1 条请求，每分钟最多 10 条。队列最多等待 60 秒，推理最多 180 秒。历史限制 12 条 / 8000 字，请求体限制 64 KB，输出最多 512 token。主机模型不可用时页面会提示重试。多人长时间使用仍需实际压测，CPU / GPU 内存由同一主机承担；私人助手的其他进程不受朋友网关的单独队列控制，重负载时应先暂停私人聊天。

在主机执行：

```powershell
# 默认使用本机 config.toml 的模型；先确保 Ollama 已运行
./start-ollama.cmd
# 为每个朋友创建独立令牌；只显示一次，复制给对应朋友
./jarvis.cmd friends invite friend-a
./jarvis.cmd friends invite friend-b
# 测试仅绑定本机，不会自动暴露网络
./jarvis.cmd friends serve --model qwen2.5:0.5b --port 8001
# 打开 http://127.0.0.1:8001，输入邀请令牌即可聊天
./jarvis.cmd friends list
# 撤销后新请求立即失效，已经生成中的一次回复可能完成
./jarvis.cmd friends revoke friend-a
```

要用你现有的更大模型，把 `--model` 改成实际安装名，例如 `qwen3.5:9b`。无需切换你私人助手的默认配置。令牌的 SHA256 摘要保存在 `friends-members.json`，文件不进入分发包。停止服务器用 Ctrl+C。当前版本只提供专用网页协议，不直接暴露 OpenAI `/v1/chat/completions`，也不共享整个私人助手网页。

远程建议先采用私有网络：主机和朋友加入同一个 Tailscale 网络，主机通过 [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) 转发这个独立服务：

```powershell
tailscale serve --bg http://127.0.0.1:8001
```

朋友打开 Serve 给出的 HTTPS 地址并输入自己的令牌。网络成员访问规则由 Tailscale 设置控制，应用令牌仍然必须验证。也可以自行配置有 HTTPS 的反向代理。局域网试用可使用 `friends serve --host 0.0.0.0 --port 8001`，并只为该端口 / 私有网络范围配置 Windows 防火墙。HTTP 局域网测试不等于加密远程接入；不要将私人服务 8000 或 Ollama 11434 作为朋友入口。此次开发没有修改防火墙、路由器、Tailscale 配置，也没有开启公网服务。

后续可以继续加入 HTTPS 下的浏览器麦克风、服务器 ASR / TTS、每人的持久会话、管理员配额、等待状态和负载监控。当前先验证文字聊天这一条完整链路。

## 重新生成分享包

制作者在 `D:\Jarvis` 中运行：

```powershell
# 新桌面启动器单独输出，不中断当前使用中的应用
./build-desktop.ps1 -OutputDirectory D:\Jarvis\dist\share-desktop
# 引导包：不带 LLM / 语音权重，接 API 的朋友可使用
./src/.venv/Scripts/python.exe ./src/deploy/share/build_package.py --root D:\Jarvis --output D:\Jarvis\dist\JARVIS-Share-Bootstrap.zip --desktop
# 带轻量中文权重的包：只收集 Qwen2.5 0.5B 和中文语音资源
./src/.venv/Scripts/python.exe ./src/deploy/share/build_package.py --root D:\Jarvis --output D:\Jarvis\dist\JARVIS-Share-Lite-Zh.zip --desktop --lite --speech
```

打包脚本依照 `deploy/share/runtime` 中的可复用启动脚本收集文件；模型仅按一个已选 Ollama manifest 的 SHA256 内容寻址，不会复制整个 `models/ollama`。包内包含逐文件 SHA256 清单。生成前如修改根目录启动脚本，需同步到该 runtime 模板目录。源代码变更和模型权重应在分发前重新构建与校验。

引导包不会复制 `.venv`、GPU 工具链、Qwen-TTS、其他大型模型、用户私有数据，也不预装完整 Ollama 运行时。图形向导会按选择自动下载 Ollama，或连接用户提供的兼容 API。已经运行的系统 Ollama 可能使用另一处模型目录；这种情况下向导会下载模型到该服务实际使用的位置。带权重包仍需联网安装 Python 依赖，因此不能称为完全离线版。第三方许可与来源见 `THIRD_PARTY_NOTICES.md`。
