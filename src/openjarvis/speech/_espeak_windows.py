"""Keep eSpeak's narrow-character file API away from Unicode Windows paths."""

import os


def prepare_espeak_windows():
    if os.name != "nt":
        return
    from phonemizer.backend.espeak.api import EspeakAPI

    original = EspeakAPI.__init__
    if getattr(original, "_jarvis_windows_path", False):
        return

    def initialize(self, library, data_path):
        if data_path is not None and not str(data_path).isascii():
            # Workers run in the installation directory. A relative path avoids
            # the ANSI fopen crash without changing the shared process cwd.
            relative = os.path.relpath(str(data_path))
            if not relative.isascii():
                raise RuntimeError(
                    "英文语音需要从安装目录启动。请使用贾维斯桌面快捷方式。"
                )
            data_path = relative
        original(self, library, data_path)

    initialize._jarvis_windows_path = True
    EspeakAPI.__init__ = initialize
