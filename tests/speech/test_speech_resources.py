from openjarvis.speech.resources import catalog, installed


def test_text_only_requires_real_assets(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENJARVIS_RESOURCE_ROOT', str(tmp_path))
    result = installed()
    assert not result['tts'] and not result['asr-zh'] and not result['clone']
    assert catalog()['text_only']
    assert not any(c['available'] for c in catalog()['choices'])
