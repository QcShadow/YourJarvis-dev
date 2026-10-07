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

Version 0.1.6 offers optional Piper and Qwen resources through the speech
download wizard. The default installer contains no personal recordings or
movie-inspired JARVIS reference voice.

Piper runtime 1.8.0 is from https://github.com/OHF-Voice/piper1-gpl,
Copyright The Home Assistant Authors, GPL-3.0-or-later. The optional runtime
retains its complete COPYING and dependency licenses. Corresponding upstream
source for this unmodified version is available from the project's 1.8.0 release.
Imported Piper models carry their own model/data terms; engine availability
does not grant redistribution rights for a user's model.

Qwen3-TTS-12Hz-0.6B-Base is from
https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base,
Copyright Qwen / Alibaba Cloud, Apache-2.0. The model is fetched separately at
revision 5d83992436eae1d760afd27aff78a71d676296fc with fixed sizes and SHA-256
checks. Its official model card and the full Apache-2.0 text in src/LICENSE are
retained. The isolated CPU runtime retains CPython and installed dependency
licenses and metadata. No local settings, configuration, keys, recordings,
model cache credentials, or user databases are included.
