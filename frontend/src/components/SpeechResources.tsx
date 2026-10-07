import { useEffect, useState } from 'react';
import { Mic, Volume2, Download, X } from 'lucide-react';
import { apiFetch, getBase } from '../lib/api';
import { useAppStore } from '../lib/store';

type Choice = { id: string; name: string; name_en: string; installed: boolean; available: boolean; bytes: number };

export function SpeechResources({ homepage = false }: { homepage?: boolean }) {
  const zh = useAppStore((s) => s.settings.interfaceLanguage === 'zh-CN');
  const [choices, setChoices] = useState<Choice[]>([]);
  const [textOnly, setTextOnly] = useState(false);
  const [expanded, setExpanded] = useState(!homepage);
  const [dismissed, setDismissed] = useState(() => homepage && sessionStorage.getItem('jarvis-speech-dismissed') === '1');
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const style = { background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' };
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const response = await apiFetch('/v1/speech/packs/resources');
        if (!response.ok) return;
        const result = await response.json();
        if (!disposed) {
          setChoices(result.choices); setTextOnly(result.text_only);
          const pending = JSON.parse(sessionStorage.getItem('jarvis-speech-pending') || '[]') as string[];
          if (Array.isArray(pending) && pending.length && pending.every((id) => result.choices.some((c: Choice) => c.id === id && c.installed))) {
            sessionStorage.removeItem('jarvis-speech-pending');
            useAppStore.getState().updateSettings({
              ...(pending.includes('asr-zh') ? { recognitionLanguage: 'zh' as const } : pending.includes('asr-en') ? { recognitionLanguage: 'en' as const } : {}),
              ...(pending.includes('tts') ? { voiceOutputEnabled: true } : {}),
            });
          }
        }
      } catch { /* Keep text chat available if resource status cannot be read. */ }
    };
    void load();
    return () => { disposed = true; };
  }, []);
  if (!choices.length || (homepage && (!textOnly || dismissed))) return null;
  const total = choices.filter((c) => selected.includes(c.id)).reduce((sum, c) => sum + c.bytes, 0);
  const bridge = (window as Window & { chrome?: { webview?: { postMessage: (data: unknown) => void } } }).chrome?.webview;
  const remote = !!getBase() && new URL(getBase(), location.href).origin !== location.origin;
  return <section className="m-3 rounded-2xl border p-4 text-sm shadow-sm" style={style} data-i18n-ignore aria-label={zh ? '语音资源' : 'Speech resources'}>
    <div className="flex items-start gap-3">
      <div className="rounded-xl p-2" style={{ background: 'var(--color-bg-tertiary)' }}><Mic size={20} /></div>
      <div className="flex-1"><h3 className="font-semibold">{homepage ? zh ? '现在可以为 JARVIS 开启语音' : 'Add speech to JARVIS' : zh ? '语音资源 · 按需安装' : 'Optional speech resources'}</h3>
        <p className="mt-1 text-xs opacity-70">{zh ? '语音输入和播报可分别选择，稍后也可在设置中安装。个人配置会保留。' : 'Choose input and output separately, here or later in Settings. Personal settings are preserved.'}</p></div>
      {homepage && <button type="button" aria-label={zh ? '稍后提醒' : 'Dismiss for this session'} onClick={() => { sessionStorage.setItem('jarvis-speech-dismissed', '1'); setDismissed(true); }}><X size={16} /></button>}
    </div>
    {!expanded && <button className="mt-3 flex items-center gap-2 rounded-lg border px-3 py-2" style={{ borderColor: 'var(--color-border)' }} onClick={() => setExpanded(true)}><Volume2 size={16} />{zh ? '选择语音功能' : 'Choose speech features'}</button>}
    {expanded && <div className="mt-4 space-y-2">
      {choices.map((choice) => <label key={choice.id} className="flex cursor-pointer items-center gap-3 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', opacity: choice.installed ? 0.65 : 1 }}>
        <input type="checkbox" disabled={choice.installed || !choice.available || pending} checked={selected.includes(choice.id)} onChange={(e) => setSelected((s) => e.target.checked ? [...s, choice.id] : s.filter((id) => id !== choice.id))} />
        <span className="flex-1">{zh ? choice.name : choice.name_en}</span><span className="text-xs opacity-70">{choice.installed ? zh ? '已安装' : 'Installed' : !choice.available ? zh ? '资源暂不可用' : 'Unavailable' : `${(choice.bytes / 1024 ** 3).toFixed(2)} GB`}</span>
      </label>)}
      {selected.includes('clone') && <p className="text-xs opacity-70">{zh ? '录音创建音色使用本地 Qwen3-TTS 模型。建议 16 GB 内存，CPU 首次生成可能需要数分钟；无需显卡。' : 'Voice creation runs locally with Qwen3-TTS. 16 GB RAM recommended; initial CPU generation may take minutes. No GPU required.'}</p>}
      {!bridge || remote ? <p className="text-xs opacity-70">{zh ? '请在本机朋友版桌面窗口中打开此页面，使用下载向导。' : 'Open this page in the local friends-edition desktop app to use the download wizard.'}</p> : <button type="button" disabled={!selected.length || pending} className="mt-3 flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-white disabled:opacity-40" onClick={() => {
        setError(''); setPending(true);
        try { sessionStorage.setItem('jarvis-speech-pending', JSON.stringify(selected)); bridge.postMessage({ type: 'install-speech', choices: selected }); }
        catch (reason) { setError(String(reason)); setPending(false); }
      }}><Download size={16} />{pending ? zh ? '正在打开下载向导…' : 'Opening download wizard…' : zh ? `下载所选资源 · 最多 ${(total / 1024 ** 3).toFixed(2)} GB` : `Download selected · up to ${(total / 1024 ** 3).toFixed(2)} GB`}</button>}
      <p className="text-xs opacity-60">{zh ? '共享运行环境只下载一次。安装期间会暂停后台，完成或退出向导后自动恢复。' : 'Shared dependencies download once. The backend pauses during installation and resumes when the wizard closes.'}</p>
      {error && <p role="alert">{error}</p>}
    </div>}
  </section>;
}
