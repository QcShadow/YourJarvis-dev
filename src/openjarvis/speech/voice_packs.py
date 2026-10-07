"""User-owned, data-only voice assets; independent of shared model resources."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import stat
import threading
import uuid
import wave
import zipfile
from contextlib import contextmanager
from pathlib import PurePosixPath

from openjarvis.core.paths import get_config_dir, get_resource_dir

MAX_UPLOAD = 256 * 1024 * 1024
MAX_AUDIO = 12 * 1024 * 1024
_LOCK = threading.RLock()
_ID = re.compile(r"user-[0-9a-f]{32}\Z")
_USERS: dict[str, int] = {}


@contextmanager
def lease(pack_id):
    if not pack_id.startswith("user-"):
        yield
        return
    with _LOCK:
        read_manifest(pack_id)
        _USERS[pack_id] = _USERS.get(pack_id, 0) + 1
    try:
        yield
    finally:
        with _LOCK:
            _USERS[pack_id] -= 1
            if not _USERS[pack_id]:
                _USERS.pop(pack_id)


def packs_dir():
    return get_config_dir() / "data/voice-packs"


def pack_path(pack_id):
    if not _ID.fullmatch(pack_id):
        raise ValueError("Invalid voice pack ID")
    path = packs_dir() / pack_id
    if path.is_symlink() or (
        path.exists() and path.resolve().parent != packs_dir().resolve()
    ):
        raise ValueError("Invalid voice pack directory")
    return path


def _name(name):
    if not isinstance(name, str):
        raise ValueError("音色名称必须是文字")
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError("音色名称需要 1–80 个字符")
    return name


def validate_audio(data):
    if len(data) > MAX_AUDIO:
        raise ValueError("参考录音不能超过 12 MB")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            rate, channels, width = (
                audio.getframerate(),
                audio.getnchannels(),
                audio.getsampwidth(),
            )
            frames = audio.getnframes()
            if channels not in (1, 2) or width != 2 or not 8000 <= rate <= 96000:
                raise ValueError("请使用 8–96 kHz、16 位 PCM、单声道或双声道 WAV")
            if not 1 <= frames / rate <= 30:
                raise ValueError("参考录音需要 1–30 秒，建议 5–15 秒")
            samples = audio.readframes(frames)
            if len(samples) != frames * channels * width:
                raise ValueError("参考录音不完整")
            import numpy as np

            values = np.frombuffer(samples, dtype="<i2").astype(np.float32)
            if float(np.sqrt(np.mean(values**2))) < 10:
                raise ValueError("参考录音没有有效声音")
    except (wave.Error, EOFError) as exc:
        raise ValueError("无法读取 WAV；请使用 16 位 PCM 格式") from exc


def _piper_config(data):
    try:
        config = json.loads(data)
        code = config["language"]["code"].lower().replace("_", "-")
        language = code.split("-")[0]
        if language not in {"zh", "en"}:
            raise ValueError("第一版 Piper 导入支持中文和英文模型")
        if not 8000 <= config["audio"]["sample_rate"] <= 96000:
            raise ValueError("Invalid sample rate")
        if (
            not isinstance(config["phoneme_id_map"], dict)
            or not config["phoneme_id_map"]
        ):
            raise ValueError("Missing phoneme map")
        if config.get("phoneme_type", "espeak") != "espeak":
            raise ValueError("第一版支持 espeak 类型的 Piper 模型")
        if not isinstance(config["espeak"]["voice"], str):
            raise ValueError("Missing espeak voice")
        count = config.get("num_speakers", 1)
        if not isinstance(count, int) or not 1 <= count <= 10000:
            raise ValueError("Invalid speaker count")
        for key in ("length_scale", "noise_scale", "noise_w"):
            value = config.get("inference", {}).get(key, 1.0)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Invalid inference configuration")
        return language, count
    except (
        KeyError,
        TypeError,
        AttributeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Piper 配置文件不完整或格式错误") from exc


def _json(data):
    if len(data) > 256 * 1024:
        raise ValueError("配置文件过大")
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("配置必须是 JSON 对象")
        return result
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("配置文件不是有效的 JSON") from exc


def unpack(data):
    """Read bounded ZIP members without extracting paths from the archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 16 or sum(i.file_size for i in infos) > MAX_UPLOAD:
                raise ValueError("语音包文件数量或解压大小超出限制")
            files = {}
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                if (
                    "\\" in name
                    or ":" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or stat.S_ISLNK(info.external_attr >> 16)
                ):
                    raise ValueError("语音包包含非法路径")
                if info.is_dir():
                    continue
                if name in files or info.flag_bits & 1:
                    raise ValueError("语音包包含重复或加密文件")
                if info.file_size > max(1, info.compress_size) * 200:
                    raise ValueError("语音包压缩比例异常")
                files[name] = archive.read(info)
            manifest = _json(files.pop("manifest.json"))
            if manifest.get("schema_version") != 1:
                raise ValueError("不支持此语音包版本")
            assets = manifest.get("assets")
            if not isinstance(assets, dict) or any(
                not isinstance(p, str) or p not in files for p in assets.values()
            ):
                raise ValueError("语音包缺少声明的文件")
            if set(files) != set(assets.values()):
                raise ValueError("语音包包含未声明文件")
            return manifest, {key: files[path] for key, path in assets.items()}
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise ValueError("语音包损坏或缺少 manifest.json") from exc


def install(files, *, name="", transcript="", reference_language="zh", speaker_id=0, embedding_only=False):
    """Validate in staging, then atomically publish an immutable asset directory."""
    if not files or len(files) > 3 or sum(len(data) for _, data in files) > MAX_UPLOAD:
        raise ValueError("请选择语音文件；总大小不能超过 256 MB")
    manifest = {}
    if len(files) == 1 and files[0][0].lower().endswith((".jvoice", ".zip")):
        manifest, assets = unpack(files[0][1])
        kind = manifest.get("kind")
        name = name or manifest.get("name", "")
        expected_engine = "qwen3-tts" if kind == "reference" else "piper"
        if manifest.get("engine") != expected_engine:
            raise ValueError("不支持此语音包引擎")
        if kind == "reference" and manifest.get(
            "engine_model", "Qwen3-TTS-12Hz-0.6B-Base"
        ) != "Qwen3-TTS-12Hz-0.6B-Base":
            raise ValueError("参考音色包需要 Qwen3-TTS-12Hz-0.6B-Base")
        reference_language = manifest.get("reference_language", "zh")
        speaker_id = manifest.get("speaker_id", 0)
        embedding_only = manifest.get("embedding_only", False)
        if not isinstance(embedding_only, bool):
            raise ValueError("音色模式必须为布尔值")
    else:
        assets = {}
        for filename, data in files:
            lower = filename.lower()
            key = (
                "audio"
                if lower.endswith(".wav")
                else "transcript"
                if lower.endswith(".txt")
                else "model"
                if lower.endswith(".onnx")
                else "config"
                if lower.endswith(".json")
                else ""
            )
            if not key or key in assets:
                raise ValueError("支持 WAV＋文字、ONNX＋JSON，或 .jvoice 语音包")
            assets[key] = data
        kind = "reference" if "audio" in assets else "piper-model"
    name = _name(name)
    if kind == "reference":
        if set(assets) - {"audio", "transcript"} or "audio" not in assets:
            raise ValueError("参考录音包需要 WAV 录音")
        validate_audio(assets["audio"])
        try:
            text = (
                transcript.strip()
                or assets.get("transcript", b"").decode("utf-8-sig").strip()
            )
        except UnicodeDecodeError as exc:
            raise ValueError("对应文字需要 UTF-8 编码") from exc
        if (not text and not embedding_only) or len(text) > 3000:
            raise ValueError("请填写录音中实际说出的文字（1–3000 字符）")
        if reference_language not in {"zh", "en"}:
            raise ValueError("参考语言需要中文或英文")
        stored = {
            "reference.wav": assets["audio"],
            "reference.txt": text.encode("utf-8"),
        }
        details = {
            "engine": "qwen3-tts",
            "engine_model": "Qwen3-TTS-12Hz-0.6B-Base",
            "languages": ["zh", "en"],
            "reference_language": reference_language,
            "embedding_only": embedding_only,
            "assets": {"audio": "reference.wav", "transcript": "reference.txt"},
        }
    elif kind == "piper-model":
        if set(assets) != {"model", "config"} or not assets["model"]:
            raise ValueError("Piper 包需要 ONNX 模型和 JSON 配置")
        if len(assets["config"]) > 256 * 1024:
            raise ValueError("Piper 配置文件过大")
        language, count = _piper_config(assets["config"])
        if not isinstance(speaker_id, int) or not 0 <= speaker_id < count:
            raise ValueError("Piper speaker ID 超出模型范围")
        stored = {"voice.onnx": assets["model"], "voice.onnx.json": assets["config"]}
        details = {
            "engine": "piper",
            "languages": [language],
            "speaker_id": speaker_id,
            "assets": {"model": "voice.onnx", "config": "voice.onnx.json"},
        }
    else:
        raise ValueError("第一版仅支持参考录音包和 Piper 模型包")
    pack_id = "user-" + uuid.uuid4().hex
    result = {
        "schema_version": 1,
        "id": pack_id,
        "name": name,
        "kind": kind,
        **details,
        "hashes": {p: hashlib.sha256(data).hexdigest() for p, data in stored.items()},
    }
    with _LOCK:
        root = packs_dir()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / (".import-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            for path, data in stored.items():
                (staging / path).write_bytes(data)
            if kind == "piper-model":
                try:
                    from piper import PiperVoice
                except ImportError:
                    pass  # Keep assets manageable when the optional engine is absent.
                else:
                    try:
                        voice = PiperVoice.load(
                            str(staging / "voice.onnx"), use_cuda=False
                        )
                        del voice
                    except Exception as exc:
                        raise ValueError(
                            "Piper 模型无法加载，请检查模型与配置是否配套"
                        ) from exc
            (staging / "manifest.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            staging.rename(pack_path(pack_id))
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return profile(pack_id)


def read_manifest(pack_id):
    path = pack_path(pack_id)
    try:
        value = _json((path / "manifest.json").read_bytes())
    except FileNotFoundError as exc:
        raise ValueError("音色不存在") from exc
    if value.get("id") != pack_id or value.get("kind") not in {
        "reference",
        "piper-model",
    }:
        raise ValueError("音色元数据损坏")
    expected = (
        {"reference.wav", "reference.txt"}
        if value["kind"] == "reference"
        else {"voice.onnx", "voice.onnx.json"}
    )
    if not isinstance(value.get("hashes"), dict) or set(value["hashes"]) != expected:
        raise ValueError("音色文件校验信息损坏")
    if value.get("languages") not in (["zh"], ["en"], ["zh", "en"]):
        raise ValueError("音色语言信息损坏")
    return value


def verify_assets(pack_id):
    value = read_manifest(pack_id)
    root = pack_path(pack_id)
    for filename, expected in value["hashes"].items():
        file = root / filename
        if file.is_symlink():
            raise ValueError("音色文件路径异常")
        try:
            with file.open("rb") as stream:
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                actual = digest.hexdigest()
        except OSError as exc:
            raise ValueError("音色文件缺失") from exc
        if actual != expected:
            raise ValueError("音色文件已经变更，请重新导入")


def profile(pack_id):
    value = read_manifest(pack_id)
    root = pack_path(pack_id)
    reference = value["kind"] == "reference"
    required = (
        ("reference.wav", "reference.txt")
        if reference
        else ("voice.onnx", "voice.onnx.json")
    )
    assets_ok = all(
        (root / p).is_file() and not (root / p).is_symlink() for p in required
    )
    if reference:
        from openjarvis.speech.jarvis_runtime import voice_runtime

        resources = get_resource_dir()
        python, _, _ = voice_runtime(resources)
        engine_ok = python.is_file() and all(
            (resources / p).is_file()
            for p in (
                "scripts/qwen_tts_server.py",
                "models/speech/qwen3-tts-0.6b-base/model.safetensors",
                "models/speech/qwen3-tts-0.6b-base/speech_tokenizer/model.safetensors",
            )
        )
    else:
        import importlib.util

        engine_ok = importlib.util.find_spec("piper") is not None
    return {
        "id": pack_id,
        "voice_id": pack_id,
        "name": value["name"],
        "backend": "qwen-reference" if reference else "piper",
        "kind": value["kind"],
        "languages": value["languages"],
        "characters": ["jarvis-local", "mcu-jarvis"],
        "experimental": reference,
        "user_owned": True,
        "installed": assets_ok and engine_ok,
        "status": "ready"
        if assets_ok and engine_ok
        else "missing-engine"
        if assets_ok
        else "invalid-assets",
        "note": "参考录音音色按需加载；CPU 合成可能较慢。"
        if reference and engine_ok
        else "请安装对应语音引擎和基础模型。"
        if not engine_ok
        else "",
        "_pack_root": str(root),
        "_version": hashlib.sha256(
            json.dumps(value["hashes"], sort_keys=True).encode()
        ).hexdigest(),
        "_speaker_id": value.get("speaker_id", 0),
        "_embedding_only": value.get("embedding_only", False),
    }


def public_profile(value):
    return {k: v for k, v in value.items() if not k.startswith("_")}


def catalog():
    with _LOCK:
        root = packs_dir()
        if not root.is_dir():
            return []
        result = []
        for path in sorted(root.iterdir()):
            if _ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                try:
                    result.append(public_profile(profile(path.name)))
                except (ValueError, OSError, KeyError, TypeError):
                    continue
        return result


def rename(pack_id, name):
    with _LOCK:
        value = read_manifest(pack_id)
        value["name"] = _name(name)
        path = pack_path(pack_id)
        temporary = path / ".manifest.tmp"
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path / "manifest.json")
    return public_profile(profile(pack_id))


def export(pack_id):
    with _LOCK:
        value = read_manifest(pack_id)
        path = pack_path(pack_id)
        buffer = io.BytesIO()
        value.pop("id", None)
        filenames = (
            ("reference.wav", "reference.txt")
            if value["kind"] == "reference"
            else ("voice.onnx", "voice.onnx.json")
        )
        with zipfile.ZipFile(
            buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            archive.writestr(
                "manifest.json", json.dumps(value, ensure_ascii=False, indent=2)
            )
            for filename in filenames:
                file = path / filename
                if file.is_symlink():
                    raise ValueError("Invalid asset path")
                archive.write(file, filename)
        return buffer.getvalue()


def delete(pack_id):
    with _LOCK:
        if _USERS.get(pack_id):
            raise RuntimeError("音色正在生成或播放，请等待完成后再删除")
        path = pack_path(pack_id)
        read_manifest(pack_id)
        shutil.rmtree(path)
