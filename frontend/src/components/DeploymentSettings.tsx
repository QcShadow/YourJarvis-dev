import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import { useAppStore } from '../lib/store';

type Profile = 'lite' | 'balanced' | 'custom-local' | 'api' | 'remote-host';
type Preset = { model: string; description: string; max_tokens: number; recommended_ram_gb?: number; download_gb?: number };
type Deployment = { engine: string; profile?: Profile; model: string; base_url: string; local_base_url?: string; portable_client?: boolean; has_api_key: boolean; ram_gb: number; restart_required?: boolean; presets: Record<Profile, Preset> };

export function DeploymentSettings({ zh }: { zh: boolean }) {
  const [data, setData] = useState<Deployment | null>(null);
  const [profile, setProfile] = useState<Profile>('custom-local');
  const [model, setModel] = useState('');
  const [url, setUrl] = useState('');
  const [key, setKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const fieldStyle = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };

  useEffect(() => {
    let active = true;
    apiFetch('/v1/deployment/settings').then(async response => {
      if (!response.ok) throw new Error(zh ? '请在主机本地打开设置；首次配置可运行 setup-jarvis.cmd。' : 'Open settings on the host computer, or run setup-jarvis.cmd for first-run setup.');
      const value = await response.json() as Deployment;
      if (!active) return;
      setData(value); setModel(value.model); setUrl(value.base_url || 'http://127.0.0.1:11434');
      setProfile(value.profile || (value.engine === 'api' ? 'api' : 'custom-local'));
      if (value.restart_required) setMessage(zh ? '已保存的模型配置需重启后端后生效。' : 'Restart the backend to apply the saved model configuration.');
    }).catch(error => { if (active) { setFailed(true); setMessage(error.message); } });
    return () => { active = false; };
  }, [zh]);

  const choose = (next: Profile) => {
    setProfile(next); setMessage('');
    if (data?.presets[next].model) setModel(data.presets[next].model);
    if (next === 'api' || next === 'remote-host') { setUrl(''); setKey(''); }
    if (next === 'api') setModel('');
    if (next !== 'api' && next !== 'remote-host') setUrl(data?.local_base_url || 'http://127.0.0.1:11434');
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage(''); setFailed(false);
    try {
      const response = await apiFetch('/v1/deployment/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, model, base_url: url, api_key: key || null, clear_api_key: clearKey }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(typeof result.detail === 'string' ? result.detail : `Save failed (${response.status})`);
      }
      const saved = await response.json() as { model: string };
      useAppStore.getState().updateSettings({
        defaultModel: saved.model,
        maxTokens: data?.presets[profile].max_tokens || 1024,
        automaticModelRouting: profile !== 'lite' && profile !== 'api' && profile !== 'remote-host',
      });
      setData(current => current ? { ...current, has_api_key: clearKey ? false : !!key || current.has_api_key } : current);
      setKey(''); setClearKey(false);
      setMessage(data?.portable_client
        ? (zh ? '已保存。点击下方「应用并重启模型服务」后生效；聊天记录和其他设置会保留。' : 'Saved. Apply and restart the model service below; your history and settings are preserved.')
        : (zh ? '已保存并备份旧配置。重启 JARVIS 后端后生效。本地模型需先用 ollama.cmd pull 模型名 安装。' : 'Saved with a config backup. Restart the JARVIS backend to apply. Install local models first with ollama.cmd pull MODEL.'));
    } catch (error) { setFailed(true); setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };

  return <section className="rounded-xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
    <h3 className="text-sm font-semibold mb-3">{zh ? '模型与首次配置预设' : 'Model and setup presets'}</h3>
    {data && <form onSubmit={save} className="space-y-3 text-sm">
      <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{zh ? `本机内存 ${data.ram_gb} GB。小模型可用 CPU；完整客户端建议 8 GB 起，16 GB 更舒适。切换模型来源不会删减界面或功能，执行效果取决于模型能力。硬件建议为估算。` : `Host RAM: ${data.ram_gb} GB. Full client: estimated 8 GB minimum, 16 GB recommended. All model sources use the same interface and features; execution quality depends on the model.`}</p>
      <label className="block">{zh ? '模型方案' : 'Model profile'}
        <select aria-label={zh ? '模型方案' : 'Model profile'} value={profile} onChange={event => choose(event.target.value as Profile)} className="w-full mt-1 rounded-lg px-3 py-2" style={fieldStyle}>
          <option value="lite">{zh ? '轻量中文 · Qwen2.5 0.5B · 约 398 MB' : 'Lite Chinese · Qwen2.5 0.5B · ~398 MB'}</option>
          <option value="balanced">{zh ? '中文聊天 · Qwen3 1.7B · 约 1.4 GB' : 'Chinese chat · Qwen3 1.7B · ~1.4 GB'}</option>
          <option value="custom-local">{zh ? '已有 Ollama 模型' : 'Existing Ollama model'}</option>
          <option value="remote-host">{zh ? '连接 JARVIS 远程主机' : 'Connect to a remote JARVIS host'}</option>
          <option value="api">{zh ? 'LLM API / 本地 OpenAI 兼容服务' : 'LLM API / local OpenAI-compatible server'}</option>
        </select>
      </label>
      <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{data.presets[profile].description}</p>
      <label className="block">{zh ? '完整模型 ID' : 'Full model ID'}<input required maxLength={256} value={model} onChange={event => setModel(event.target.value)} className="w-full mt-1 rounded-lg px-3 py-2" style={fieldStyle} /></label>
      <label className="block">{zh ? '服务地址' : 'Server URL'}<input required type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder={profile === 'remote-host' ? 'http://主机地址:8001/v1' : profile === 'api' ? 'http://localhost:1234/v1' : data.local_base_url || 'http://127.0.0.1:11434'} className="w-full mt-1 rounded-lg px-3 py-2" style={fieldStyle} /></label>
      {profile === 'remote-host' && <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{zh ? '填写主机共享入口与邀请令牌，模型 ID 保留 host-model。主机负责推理，文件、工具和记忆属于你自己的电脑。' : 'Enter the shared gateway and invitation token. Keep model ID host-model. The host runs inference; files, tools and memory stay on your computer.'}</p>}
      {(profile === 'api' || profile === 'remote-host') && <>
        <label className="block">{zh ? (profile === 'remote-host' ? '邀请令牌' : 'API 密钥（本地无密钥服务可留空）') : (profile === 'remote-host' ? 'Invitation token' : 'API key (optional for a local server)')}<input type="password" autoComplete="off" value={key} disabled={clearKey} onChange={event => setKey(event.target.value)} placeholder={data.has_api_key ? (zh ? '已保存；留空保留现有密钥' : 'Saved; leave blank to keep it') : ''} className="w-full mt-1 rounded-lg px-3 py-2" style={fieldStyle} /></label>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={clearKey} onChange={event => { setClearKey(event.target.checked); setKey(''); }} />{zh ? '清除已保存的 API 密钥' : 'Clear the saved API key'}</label>
      </>}
      <button disabled={busy} type="submit" className="px-3 py-2 rounded-lg cursor-pointer disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'white' }}>{busy ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存模型配置' : 'Save model configuration')}</button>
      {data.portable_client && <button type="button" disabled={busy} onClick={() => {
        const desktop = window as unknown as { chrome?: { webview?: { postMessage: (value: object) => void } } };
        if (desktop.chrome?.webview) desktop.chrome.webview.postMessage({ type: 'restart-backend' });
        else setMessage(zh ? '请从托盘退出 JARVIS Link 后重新打开应用。' : 'Quit JARVIS Link from the tray and reopen it.');
      }} className="ml-3 px-3 py-2 rounded-lg cursor-pointer" style={fieldStyle}>{zh ? '应用并重启模型服务' : 'Apply and restart model service'}</button>}
      <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{zh ? '语音和模型分别配置。中文轻量语音提供云健、晓晓；其他声音、图像生成等模型可自行配置，所有功能入口均保留。' : 'Configure voice independently of your LLM. All feature controls remain available; additional voice and image models can be configured separately.'}</p>
    </form>}
    {message && <p role="status" className="text-xs mt-3" style={{ color: failed ? 'var(--color-error)' : 'var(--color-text-secondary)' }}>{message}</p>}
  </section>;
}
