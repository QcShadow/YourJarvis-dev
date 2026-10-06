# 完整版离线依赖和联网来源

发布包已内置 Python 3.12、CPU PyTorch 和已安装 Python 依赖、Ollama CPU 运行时、固定 WebView2、Playwright Chromium、完整前端资源（含字体）、Qwen2.5 0.5B、SenseVoice INT8、Kokoro 82M 中英声音、Whisper small.en。使用者首次运行不执行 pip、uv、npm、模型 pull 或浏览器下载。

| 资源 | 构建机器的来源 | 使用者需下载吗 |
| --- | --- | --- |
| Python / Python 包 | GitHub Python standalone、PyPI / files.pythonhosted.org | 不需要 |
| CPU PyTorch | download.pytorch.org | 不需要 |
| Qwen 模型 | registry.ollama.ai 的模型存储/CDN | 不需要 |
| SenseVoice / Kokoro / Whisper | Hugging Face、其 CDN / xet 存储 | 不需要 |
| 固定 WebView2 | 微软 msedge.sf.dl.delivery.mp.microsoft.com | 不需要 |
| Playwright Chromium | cdn.playwright.dev / Chrome for Testing 存储 | 不需要 |
| 高级声音 / 图像模型 / 更大 LLM | 取决于用户选择，常见 Hugging Face、GitHub、Ollama | 可选，默认包不依赖它们 |
| 联网搜索、用户 API、远程主机 | 用户配置的服务域名 / 主机地址 | 不是安装依赖，按功能需要联网 |

上述构建来源部分可能在不同网络不可访问；因此下载在发布者机器完成，所有默认运行资源一起打包。不要让无法访问这些地址的用户先安装「联网 bootstrap 版」。

Python 依赖列表和版本以包内 `runtimes/python/Lib/site-packages/*.dist-info/METADATA` 为准。全部发布文件有 package-manifest.json 中的 SHA256，ZIP 有独立 .sha256 文件。包不含开发者配置、邀请令牌、API 密钥、私人记忆或已有 WebView 资料。

第三方许可见 THIRD_PARTY_NOTICES.md 以及各模型、运行时和 Python 包自带的许可。固定 WebView2 使用微软许可，更新由发布者随包提供；大模型与扩展由用户自行配置。参考：[微软 WebView2 分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)、[Qwen 官方模型及许可](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)。
