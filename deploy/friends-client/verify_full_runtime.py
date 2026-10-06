"""Exercise packaged speech/memory/LLM using only this client's local backend."""
import argparse
import json
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
url = json.loads((root / "data/client-ready.json").read_text())["url"]
with httpx.Client(base_url=url, trust_env=False, timeout=180) as client:
    assert client.get("/health").status_code == 200
    settings = client.get("/v1/deployment/settings").json()
    assert settings["portable_client"]
    info = client.get("/v1/info").json()
    assert info["agent"] == "orchestrator"
    assert info["engine"] == "ollama"
    stored = client.post("/v1/memory/store", json={"content": "便携客户端测试记忆：绿茶标记42"})
    assert stored.status_code == 200, stored.text
    memory = client.post("/v1/memory/search", json={"query": "绿茶标记42", "top_k": 3})
    assert memory.status_code == 200, memory.text
    assert "绿茶" in memory.text
    voice = client.post("/v1/speech/synthesize", json={
        "text": "你好，我是你的本地助手。", "voice_profile": "kokoro-zh-yunjian",
        "output_language": "zh",
    })
    assert voice.status_code == 200, voice.text[:200]
    assert voice.content.startswith(b"RIFF")
    (root / "qa-chinese.wav").write_bytes(voice.content)
    recognition = client.post("/v1/speech/transcribe", files={
        "file": ("qa-chinese.wav", voice.content, "audio/wav"),
    }, data={"language": "zh"})
    assert recognition.status_code == 200, recognition.text
    assert "本地助手" in recognition.json()["text"], recognition.text
    english = client.post("/v1/speech/synthesize", json={
        "text": "Hello, I am your local assistant.", "voice_profile": "kokoro-en-george",
        "output_language": "en",
    })
    assert english.status_code == 200, english.text[:200]
    assert english.content.startswith(b"RIFF")
    (root / "qa-english.wav").write_bytes(english.content)
    en_recognition = client.post("/v1/speech/transcribe", files={
        "file": ("qa-english.wav", english.content, "audio/wav"),
    }, data={"language": "en"})
    assert en_recognition.status_code == 200, en_recognition.text
    assert "assistant" in en_recognition.json()["text"].lower(), en_recognition.text
    result = {"info": info, "memory": memory.json(), "chinese": recognition.json(), "english": en_recognition.json(),
              "chinese_wav_bytes": len(voice.content), "english_wav_bytes": len(english.content)}
    (root / "full-runtime-qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
