# Included components and model sources

OpenJarvis source is Apache-2.0; the full license is retained in `src/LICENSE`.
Modified components in this distribution add portable setup presets, configurable
API inference, Windows launchers and a separate friends chat gateway.

Optional Qwen2.5 0.5B weights come from the official Ollama distribution:
https://ollama.com/library/qwen2.5:0.5b and the original model publisher:
https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct (Qwen / Alibaba Cloud,
Apache-2.0). The model's full license is retained as the license blob referenced
by its bundled manifest. Parameter/content hashes are preserved; weights are
not modified. The full Apache-2.0 license text is also available in `src/LICENSE`.

Optional SenseVoice ONNX INT8 assets come from:
https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
and https://github.com/FunAudioLLM/SenseVoice. Its `LICENSE` and `README.md`
are included alongside the selected weights.

Optional Kokoro-82M weights come from https://huggingface.co/hexgrad/Kokoro-82M
(hexgrad, Apache-2.0). The upstream model card and voice notes are retained in
the Hugging Face snapshot. See that card for training-data acknowledgements
and Creative Commons attribution. The selected snapshot weights are unchanged.

The bootstrapper uv is from https://github.com/astral-sh/uv (MIT or Apache-2.0).
This archive uses the Apache-2.0 option; the full license text is retained in
`src/LICENSE`. Copyright Astral Software Inc. See the upstream project for
notices for its bundled dependencies.

Version 0.1.4 reuses the immutable v0.1.3 Windows x64 CPython 3.12.14 distribution and
clean, explicitly built text/voice dependency environments as immutable resource
packs. CPython's LICENSE and dependency .dist-info metadata/licenses are retained.
The installer replaces uv's absolute-path Windows redirector with CPython's
stock venv launcher and rewrites the environment's interpreter home and editable
application source path for the recipient's chosen directory. No builder config,
credentials, logs or personal state are included. Generated console entry points
with builder paths are excluded; launch uses python -m openjarvis.cli.

The CPU Ollama runtime is mirrored with its MIT LICENSE and bundled library
notices. GPU-specific CUDA/Vulkan directories are excluded from the CPU pack.

Optional Microsoft.Web.WebView2 SDK redistributable assemblies come from the
Microsoft WebView2 SDK and are governed by Microsoft's SDK terms:
https://www.nuget.org/packages/Microsoft.Web.WebView2/
The unmodified, Microsoft-signed Evergreen x64 standalone runtime installer is
mirrored as an optional resource and installed only when the runtime is missing.

The experimental movie-inspired Piper JARVIS voice, Qwen-TTS weights and their
isolated runtime are not included in the default sharing presets or archive.
