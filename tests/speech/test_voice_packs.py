"""Voice packages are bounded assets, portable and isolated by model identity."""

import asyncio
import io
import json
import stat
import threading
import wave
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from openjarvis.speech import voice_packs
from openjarvis.speech.profiles import (
    profile_backend,
    resolve_profile,
    synthesize_profile,
)


def recording(seed=1):
    buffer = io.BytesIO()
    samples = np.random.default_rng(seed).integers(
        -1000, 1000, size=24000, dtype=np.int16
    )
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(samples.astype("<i2").tobytes())
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENJARVIS_VOICE_STATE_PATH", raising=False)
    return tmp_path


def reference(name="我的声音", seed=1):
    return voice_packs.install(
        [("reference.wav", recording(seed))], name=name, transcript="这就是录音内容。"
    )


def test_reference_export_import_and_relocation(library, monkeypatch):
    first = reference()
    assert resolve_profile(first["id"], "en")["_output_language"] == "en"
    exported = voice_packs.export(first["id"])
    second = voice_packs.install([("voice.jvoice", exported)])
    assert first["id"] != second["id"]
    assert second["name"] == first["name"]
    voice_packs.rename(second["id"], "新名字")
    assert voice_packs.catalog()[1]["name"] in {"我的声音", "新名字"}
    # Moving the state root must not preserve a stale absolute asset path.
    moved = library.with_name(library.name + "-moved")
    library.rename(moved)
    monkeypatch.setenv("OPENJARVIS_HOME", str(moved))
    selected = resolve_profile(second["id"], "zh")
    assert selected["_pack_root"].startswith(str(moved))
    assert all(not key.startswith("_") for key in voice_packs.catalog()[0])
    voice_packs.verify_assets(second["id"])


def test_missing_transcript_and_silence_leave_no_installed_pack():
    with pytest.raises(ValueError, match="文字"):
        voice_packs.install([("a.wav", recording())], name="voice")
    data = bytearray(recording())
    data[44:] = bytes(len(data) - 44)
    with pytest.raises(ValueError, match="有效声音"):
        voice_packs.install([("a.wav", bytes(data))], name="voice", transcript="test")
    assert voice_packs.catalog() == []


def test_audio_only_mode_survives_sharing_without_transcript():
    value = voice_packs.install([("clean.wav", recording())], name="纯音频音色", embedding_only=True)
    assert value["_embedding_only"]
    shared = voice_packs.install([("shared.jvoice", voice_packs.export(value["id"]))])
    assert shared["_embedding_only"]
    assert (voice_packs.pack_path(shared["id"]) / "reference.txt").read_text() == ""
    voice_packs.verify_assets(shared["id"])


@pytest.mark.parametrize(
    "filename", ["../escape.wav", "/absolute.wav", "C:/escape.wav", "..\\escape.wav"]
)
def test_zip_path_traversal_rejected(filename):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, b"audio")
    with pytest.raises(ValueError, match="路径"):
        voice_packs.install([("bad.jvoice", buffer.getvalue())])


def test_zip_symlink_and_expansion_rejected(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("audio.wav")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"../outside")
    with pytest.raises(ValueError, match="路径"):
        voice_packs.unpack(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb", bytes(10000))
    monkeypatch.setattr(voice_packs, "MAX_UPLOAD", 1000)
    with pytest.raises(ValueError, match="大小"):
        voice_packs.unpack(buffer.getvalue())


def test_delete_refuses_active_generation_and_asset_mutation():
    value = reference()
    with voice_packs.lease(value["id"]):
        with pytest.raises(RuntimeError, match="正在"):
            voice_packs.delete(value["id"])
    (voice_packs.pack_path(value["id"]) / "reference.txt").write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="变更"):
        voice_packs.verify_assets(value["id"])
    voice_packs.delete(value["id"])
    assert voice_packs.catalog() == []


def piper_files(language="en_US", speakers=1):
    config = {
        "audio": {"sample_rate": 22050},
        "language": {"code": language},
        "phoneme_id_map": {"a": [1]},
        "espeak": {"voice": "en-us"},
        "num_speakers": speakers,
    }
    return [
        ("voice.onnx", b"fake-model"),
        ("voice.onnx.json", json.dumps(config).encode()),
    ]


def test_invalid_piper_model_is_not_published():
    with patch("piper.PiperVoice.load", side_effect=RuntimeError("wrong model")):
        with pytest.raises(ValueError, match="无法加载"):
            voice_packs.install(piper_files(), name="broken")
    assert voice_packs.catalog() == []
    assert not list(voice_packs.packs_dir().glob(".import-*"))


def test_piper_language_and_speaker_are_checked():
    with pytest.raises(ValueError, match="中文和英文"):
        voice_packs.install(piper_files("de_DE"), name="German")
    with pytest.raises(ValueError, match="speaker"):
        voice_packs.install(piper_files(), name="test", speaker_id=1)


@pytest.mark.anyio
async def test_two_piper_packages_never_share_model_instances():
    with patch("piper.PiperVoice.load"):
        first = voice_packs.install(piper_files(), name="one")
        second = voice_packs.install(piper_files(), name="two")
    app = SimpleNamespace(state=SimpleNamespace())
    from openjarvis.speech.piper_tts import PiperTTSBackend

    with (
        patch("openjarvis.speech.piper_tts.PiperTTSBackend.health", return_value=True),
        patch("openjarvis.core.registry.TTSRegistry.get", return_value=PiperTTSBackend),
    ):
        a, b = await asyncio.gather(
            profile_backend(app, resolve_profile(first["id"], "en")),
            profile_backend(app, resolve_profile(second["id"], "en")),
        )
    assert a is not b and a.model_path != b.model_path
    assert a.voice_id == first["id"] and b.voice_id == second["id"]


def test_reference_synthesis_receives_explicit_language_and_identity():
    value = reference()
    backend = Mock()
    backend._voice_profile_lock = threading.Lock()
    backend.synthesize.return_value = SimpleNamespace(voice_id=value["id"])
    synthesize_profile(backend, resolve_profile(value["id"], "en"), "English reply")
    assert backend.synthesize.call_args.kwargs == {
        "voice_id": value["id"],
        "language": "en",
    }
