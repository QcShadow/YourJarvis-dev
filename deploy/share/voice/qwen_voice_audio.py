"""Small, duration-preserving adjustments to the accepted Chinese voice."""

import json
import math
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / "runtimes/qwen-tts/voice_settings.json"


def generation_instruction():
    if not SETTINGS.is_file():
        return None
    return (
        json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get("instruction") or None
    )


def pitch_semitones() -> float:
    value = (
        float(json.loads(SETTINGS.read_text(encoding="utf-8-sig"))["pitch_semitones"])
        if SETTINGS.is_file()
        else 0.0
    )
    if not math.isfinite(value) or not -6 <= value <= 6:
        raise ValueError("Chinese pitch adjustment must be between -6 and 6 semitones")
    return value


def adjust_audio(samples, rate, *, speed=1.0, pitch=0.0):
    import librosa
    import numpy as np

    if pitch:
        samples = librosa.effects.pitch_shift(samples, sr=rate, n_steps=pitch)
    if speed != 1.0:
        samples = librosa.effects.time_stretch(samples, rate=speed)
    # Resampling can introduce tiny peaks above full scale; avoid PCM clipping.
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 0.999:
        samples = samples * (0.999 / peak)
    return samples


class TempoStream:
    """Keep tempo state across PCM chunks; never change the voice's pitch."""

    def __init__(self, speed):
        self.offset = 0
        self.input_frames = 0
        self.speed = speed
        self.tsm = None
        if speed != 1.0:
            from audiotsm import wsola
            from audiotsm.io.array import ArrayWriter

            self.tsm = wsola(1, speed=speed)
            self.writer = ArrayWriter(1)

    def process(self, samples, *, final=False):
        import numpy as np

        if self.tsm is None:
            return samples
        if not final:
            self.input_frames += len(samples)
        from audiotsm.io.array import ArrayReader

        self.tsm.run(
            ArrayReader(np.asarray(samples, dtype=np.float32)[None, :]),
            self.writer,
            flush=final,
        )
        audio = self.writer.data[0]
        result = audio[self.offset :]
        self.offset = len(audio)
        return result

    def finish(self):
        import numpy as np

        if self.tsm is None:
            return np.empty(0, dtype=np.float32)
        remaining = max(0, round(self.input_frames / self.speed) - self.offset)
        # Supply the analysis window with trailing silence so the last phoneme
        # is not discarded merely because no complete analysis frame remains.
        tail = self.process(np.zeros(4096, dtype=np.float32), final=True)
        return np.pad(tail, (0, max(0, remaining - len(tail))))[:remaining]
