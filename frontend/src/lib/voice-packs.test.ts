import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ apiFetch: vi.fn() }));
import { apiFetch } from './api';
import { deleteVoicePack, exportVoicePack, importVoicePack, renameVoicePack } from './voice-packs';

const send = vi.mocked(apiFetch);
beforeEach(() => send.mockReset());

describe('voice library requests', () => {
  it('uploads files as multipart, preserving Unicode names and transcript', async () => {
    send.mockResolvedValue(new Response(JSON.stringify({ id: 'user-one', name: '我的声音' }), { status: 201 }));
    await importVoicePack([new File(['wave'], 'voice.wav')], '我的声音', '录音内容。', 'zh', 0);
    const [url, request] = send.mock.calls[0];
    expect(url).toBe('/v1/speech/packs/import');
    expect(request?.headers).toBeUndefined();
    const form = request?.body as FormData;
    expect(form.get('name')).toBe('我的声音');
    expect(form.get('transcript')).toBe('录音内容。');
    expect((form.get('files') as File).name).toBe('voice.wav');
  });

  it('surfaces deletion conflicts and supports rename/export', async () => {
    send.mockResolvedValueOnce(new Response(JSON.stringify({ detail: '请先切换音色' }), { status: 409 }));
    await expect(deleteVoicePack('user-one')).rejects.toThrow('请先切换音色');
    send.mockResolvedValueOnce(new Response('{}'));
    await renameVoicePack('user-one', '新名字');
    expect(JSON.parse(send.mock.calls[1][1]?.body as string)).toEqual({ name: '新名字' });
    send.mockResolvedValueOnce(new Response(new Blob(['zip'])));
    expect(await (await exportVoicePack('user-one')).text()).toBe('zip');
  });
});
