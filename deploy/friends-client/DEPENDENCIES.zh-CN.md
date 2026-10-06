# 联网与依赖清单

## 当前离线包

| 内容 | 是否附带 | 用户首次运行需联网 |
| --- | --- | --- |
| JARVIS Link 原生入口与所有网页、字体回退 | 是 | 否 |
| Qwen2.5 0.5B Q4_K_M 模型与提示模板 | 是 | 否 |
| Ollama CPU 运行时及全部所需 CPU 库 | 是 | 否 |
| WebView2 固定版 x64 154.0.4258.48 | 是 | 否 |
| WebView2 .NET 桥接程序集 | 是 | 否 |
| .NET Framework 4.8 与 Windows 系统 DLL | 系统组件 | Windows 10 22H2 / Windows 11 已具备；不支持缺失该组件的精简系统 |
| Python、uv、pip、Torch、CUDA | 不使用 | 无需安装 |
| SenseVoice / Kokoro 语音权重 | 本版不启用语音 | 无需下载 |

本机模式不调用任何模型下载接口，运行时缺失会提示重新解压完整包。没有 CDN 字体、远程脚本或在线页面依赖。模型请求仅发往这份应用自己启动的回环服务，不使用主机开发版的 Ollama 端口。

连接共享主机必须能访问所填地址；它可以是同一局域网或私人网络，并不必然要求能访问海外网站。客户端不直接访问付费 LLM 服务商。Tailscale 的首次登录和组网需要其服务可达，无法访问时应改用已可达的 HTTPS 或局域网入口。

## 制作者重新构建时的外部来源

以下资源已在本包中备齐，用户不需要现场下载。不同地区、网络、代理和镜像的可达性不同，不能承诺不经测试就能访问：

| 上游 | 用途 | 当前用户运行时 |
| --- | --- | --- |
| ollama.com / registry.ollama.ai 及其下载 CDN | 获取模型与 CPU 运行时 | 不访问 |
| developer.microsoft.com / msedge.sf.dl.delivery.mp.microsoft.com | 获取固定 WebView2 运行时 | 不访问 |
| nuget.org 及 CDN | 获取 WebView2 SDK | 不访问 |
| github.com / raw.githubusercontent.com | 上游代码与许可证 | 不访问 |
| huggingface.co 及其 CDN | 未来语音权重、原始模型 | 当前包不需要 |
| pypi.org / files.pythonhosted.org / Python 下载源 | 完整开发版的 Python 依赖 | 当前包不需要 |

完整版开发／分享引导包的安装仍可能依赖上述网络。JARVIS Link 是单独制作的最小离线客户端，不能把它的离线结论套用于先前的 Bootstrap 包。

固定 WebView2 不自动更新，由制作者后续发布新的完整包。固定版本包分发方法遵循微软文档：https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution 。
