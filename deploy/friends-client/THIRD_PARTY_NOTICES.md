# JARVIS Link component notices

The modified application and UI source use Apache-2.0; see LICENSE and source/JARVIS-Link.cs.

Qwen2.5 0.5B weights: Qwen / Alibaba Cloud, Apache-2.0. Source: https://ollama.com/library/qwen2.5:0.5b and https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct . The upstream model manifest and license blob are preserved unchanged.

Ollama CPU runtime: MIT, copyright Ollama. Full license: runtimes/ollama/LICENSE. Sources: https://github.com/ollama/ollama . Dependent CPU libraries retain their LICENSE / NOTICE files in runtimes/ollama/lib/ollama. CUDA and Vulkan runtime folders are excluded.

Microsoft WebView2 fixed runtime 154.0.4258.48 x64 and SDK assemblies: Microsoft redistributable terms. The official package is retained in full under runtimes/webview2, including its license material. Source: https://developer.microsoft.com/en-us/microsoft-edge/webview2/ . Distribution documentation: https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution . The executable publisher signature is verified during packaging QA.

Windows and .NET Framework 4.8 are operating-system prerequisites, not redistributed as a Python environment or copied from the author's personal runtime state.

The full client additionally includes the official standalone CPython distribution (Python Software Foundation license), CPU PyTorch, Python dependencies and Playwright Chromium. Their upstream licenses and metadata are retained under runtimes/python and runtimes/playwright. The full OpenJarvis backend is included under src/src/openjarvis, with the same compiled frontend as the developer application. No developer virtualenv launchers or credentials are copied.

openjarvis_rust compiled extension: OpenJarvis, Apache-2.0; bundled to provide the same native document memory and tools as the developer build. The extension contains application code, not the developer's memories or configuration.

SenseVoice model: csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17, upstream license and README under models/speech/sensevoice. Kokoro-82M: hexgrad/Kokoro-82M, Apache-2.0; license and model card retained with the pinned cache snapshot. Whisper small.en: Systran/faster-whisper-small.en, MIT; upstream model card retained under models/speech/whisper-small.en. spaCy English resource en_core_web_sm 3.8.0: Explosion, MIT; license retained in its Python package.
