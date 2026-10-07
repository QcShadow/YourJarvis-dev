import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

export function ThirdPartyAPISettings({ zh }: { zh: boolean }) {
  const [enabled, setEnabled] = useState(false);
  const [name, setName] = useState('第三方 API');
  const [url, setUrl] = useState('');
  const [models, setModels] = useState('');
  const [key, setKey] = useState('');
  const [hasKey, setHasKey] = useState(false);
  const [clearKey, setClearKey] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [catalog, setCatalog] = useState<string[]>([]);
  const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };

  useEffect(() => {
    let active = true;
    apiFetch('/v1/deployment/third-party-api').then(async response => {
      if (!response.ok) throw new Error(zh ? '请在主机本地配置第三方 API。' : 'Configure the third-party API on the host computer.');
      const value = await response.json();
      if (!active) return;
      setEnabled(value.enabled); setName(value.name); setUrl(value.base_url); setModels(value.models.join('\n'));
      setHasKey(value.has_api_key); setReady(true);
    }).catch(error => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, [zh]);

  const submit = async (test: boolean) => {
    setBusy(true); setMessage('');
    try {
      const response = await apiFetch(`/v1/deployment/third-party-api${test ? '/test' : ''}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, name, base_url: url, models: models.split(/[\n,，]+/).map(x => x.trim()).filter(Boolean), api_key: key || null, clear_api_key: clearKey }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${response.status}`);
      if (test) {
        setCatalog(value.available_models || []);
        setMessage(`${zh ? '调用成功' : 'Connection succeeded'} · ${value.model}: ${value.reply}`);
      } else {
        setHasKey(clearKey ? false : !!key || hasKey); setKey(''); setClearKey(false);
        setMessage(zh ? `已保存。重启 JARVIS 后端后，在聊天模型列表选择「${name}」的模型。` : `Saved. Restart the JARVIS backend, then select a model under “${name}”.`);
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };

  return <section className="rounded-xl p-5 space-y-3 text-sm" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
    <h3 className="text-sm font-semibold">{zh ? '第三方 API · 补充模型来源' : 'Third-party API · additional models'}</h3>
    <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{zh ? '连接支持 OpenAI 协议的第三方服务，可与现有模型并存。自定义名称会显示在聊天模型列表中。' : 'Connect an OpenAI-compatible third-party service alongside your existing models. Its custom name appears in the chat model list.'}</p>
    {ready && <>
      <label className="flex items-center gap-2"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />{zh ? '启用第三方 API' : 'Enable third-party API'}</label>
      <label className="block">{zh ? '自定义名称' : 'Custom name'}<input maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder={zh ? '例如：中科大' : 'For example: USTC'} className="w-full mt-1 rounded-lg px-3 py-2" style={style} /></label>
      <label className="block">{zh ? '接口地址' : 'Endpoint'}<input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://api.example.com/v1" className="w-full mt-1 rounded-lg px-3 py-2" style={style} /></label>
      <label className="block">{zh ? 'API 密钥' : 'API key'}<input type="password" autoComplete="off" value={key} disabled={clearKey} onChange={e => setKey(e.target.value)} placeholder={hasKey ? (zh ? '已保存；留空保留' : 'Saved; leave blank to keep') : 'sk-…'} className="w-full mt-1 rounded-lg px-3 py-2" style={style} /></label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={clearKey} onChange={e => { setClearKey(e.target.checked); setKey(''); if (e.target.checked) setEnabled(false); }} />{zh ? '清除已保存密钥' : 'Clear saved key'}</label>
      <label className="block">{zh ? '平台模型 ID（每行一个）' : 'Platform model IDs (one per line)'}<textarea rows={3} value={models} onChange={e => setModels(e.target.value)} className="w-full mt-1 rounded-lg px-3 py-2" style={style} /></label>
      <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{zh ? '填写服务平台实际提供的模型 ID，每行一个。测试会向第一行模型发送一次短请求，可能消耗额度。更换接口地址后请填写对应服务的密钥。' : 'Enter the exact model IDs offered by your service, one per line. Testing sends one short request to the first model and may use quota. Enter the matching key when changing the endpoint.'}</p>
      {catalog.length > 0 && <div className="text-xs space-y-2"><p>{zh ? '接口返回的模型（点击添加）' : 'Models returned by the gateway (click to add)'}</p><div className="flex flex-wrap gap-2">{catalog.map(id => <button key={id} type="button" className="rounded px-2 py-1" style={style} onClick={() => setModels(current => Array.from(new Set([...current.split(/[\n,，]+/).map(x => x.trim()).filter(Boolean), id])).join('\n'))}>{id}</button>)}</div></div>}
      <div className="flex gap-3"><button type="button" disabled={busy} onClick={() => void submit(true)} className="rounded-lg px-3 py-2 disabled:opacity-50" style={style}>{zh ? '测试连接并读取模型' : 'Test and fetch models'}</button><button type="button" disabled={busy} onClick={() => void submit(false)} className="rounded-lg px-3 py-2 disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'white' }}>{busy ? (zh ? '处理中…' : 'Working…') : (zh ? '保存第三方 API 配置' : 'Save third-party API settings')}</button></div>
    </>}
    {message && <p role="status" className="text-xs whitespace-pre-wrap">{message}</p>}
  </section>;
}
