"""Enable only downloaded capabilities without rebuilding private LLM config."""
import argparse
import os
from pathlib import Path

import tomlkit


def configure(root, choices):
    os.environ['OPENJARVIS_RESOURCE_ROOT'] = str(root)
    from openjarvis.speech.resources import installed
    from openjarvis.core.credentials import secure_write_text
    ready = installed(root)
    if any(not ready[key] for key in choices):
        raise ValueError('语音资源缺少依赖或模型，请重试安装')
    path = root / 'config.toml'
    doc = tomlkit.parse(path.read_text(encoding='utf-8-sig'))
    speech = doc.setdefault('speech', tomlkit.table())
    if 'asr-zh' in choices or 'asr-en' in choices:
        speech['backend'] = 'language-routed'
        speech['language'] = 'zh' if 'asr-zh' in choices else 'en'
        speech['chinese_model'] = str(root / 'models/speech/sensevoice')
        speech['english_model'] = str(root / 'models/speech/whisper-small.en')
    if 'tts' in choices:
        speech['tts_backend'] = 'kokoro'
        speech['voice_id'] = 'zm_yunjian'
    secure_write_text(path, tomlkit.dumps(doc))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--choices', required=True)
    args = parser.parse_args()
    configure(args.root.resolve(), args.choices.split(','))
