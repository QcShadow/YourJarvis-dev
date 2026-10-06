import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

type Policy = {
  main_during_image: string;
  image_device: string; voice_idle_seconds: number; writer_idle_seconds: number;
  cpu_image_idle_seconds: number; voice_wait_seconds: number;
};
type Job = { id: string; kind: string; model: string; description: string; device: string;
  status: string; reason: string; created_at: number; started_at?: number; finished_at?: number };
type Snapshot = { settings: Policy; gpu: { total_mib: number; used_mib: number; free_mib: number } | null;
  ram: { total_mib: number; used_mib: number; free_mib: number } | null;
  deployed: { writer: boolean; image: boolean };
  services: { ollama: { models: { name: string; size_vram: number; context_length: number }[] } | null;
    voice: { loaded?: boolean; busy?: boolean; suspended?: boolean } | null;
    image: { loaded: boolean; device: string } | null };
  tasks: Job[]; agents: { id: string; name: string; model: string; status: string; activity: string }[] };
const statusLabel: Record<string, string> = { queued: '排队', waiting: '等待资源', running: '运行中',
  complete: '完成', failed: '失败', idle: '空闲', paused: '暂停' };

export function ModelScheduler() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const response = await apiFetch('/v1/model-scheduler');
        if (!response.ok) throw new Error(`调度状态读取失败 (${response.status})`);
        const snapshot: Snapshot = await response.json();
        if (active) { setData(snapshot); setPolicy(previous => previous || snapshot.settings); setError(''); }
      } catch (e) { if (active) setError(String(e)); }
      if (active) timer = setTimeout(refresh, 3000);
    };
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, []);
  const save = async () => {
    if (!policy) return;
    setSaving(true); setMessage('');
    try {
      const response = await apiFetch('/v1/model-scheduler/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(policy),
      });
      if (!response.ok) throw new Error('设置保存失败');
      setPolicy(await response.json()); setMessage('已保存；新任务使用新设置。');
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  };
  const inputStyle = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)',
    border: '1px solid var(--color-border)', borderRadius: 6, padding: '6px 10px' };
  const models = data?.services.ollama?.models || [];
  const writer = models.find(model => model.name.startsWith('jarvis-writer:'));
  const voice = data?.services.voice;
  const image = data?.services.image;
  return <div className="space-y-5" style={{ color: 'var(--color-text)' }}>
    <div>
      <h2 className="text-lg font-semibold">模型调度与任务窗口</h2>
      <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
        主助手平时使用 GPU，小说写作使用 CPU。GPU 生图可将主助手切换到 CPU、暂停语音；出图后恢复主助手，语音按需加载。
      </p>
    </div>
    {error && <p role="alert" className="text-sm" style={{ color: 'var(--color-error)' }}>{error}</p>}
    {data?.gpu && <div className="rounded-lg p-3" style={{ background: 'var(--color-bg-secondary)' }}>
      <div className="flex justify-between text-sm mb-2"><span>GPU 显存</span>
        <span>{(data.gpu.used_mib / 1024).toFixed(1)} / {(data.gpu.total_mib / 1024).toFixed(1)} GiB · 空闲 {(data.gpu.free_mib / 1024).toFixed(1)} GiB</span></div>
      <div className="h-2 rounded overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
        <div className="h-full" style={{ width: `${data.gpu.used_mib / data.gpu.total_mib * 100}%`, background: 'var(--color-accent)' }} />
      </div>
    </div>}
    {data?.ram && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>系统内存：可用 {(data.ram.free_mib / 1024).toFixed(1)} / {(data.ram.total_mib / 1024).toFixed(1)} GiB</p>}
    <div className="overflow-x-auto"><table className="w-full text-sm text-left">
      <thead><tr><th className="p-2">模型</th><th>设备</th><th>当前状态</th></tr></thead>
      <tbody>
        {models.filter(model => !model.name.startsWith('jarvis-writer:')).map(model => <tr key={model.name}>
          <td className="p-2">{model.name}</td><td>{model.size_vram ? 'GPU' : 'CPU'}</td>
          <td>已加载 · 上下文 {model.context_length}</td></tr>)}
        <tr><td className="p-2">小说助手 · Qwen3.5 4B</td><td>CPU</td><td>{writer ? '已加载' : data?.deployed.writer ? '待机，按需加载' : '模型下载中或未部署'}</td></tr>
        <tr><td className="p-2">生图 · LCM Dreamshaper</td><td>{image?.loaded ? image.device.toUpperCase() : (data?.settings.image_device === 'cpu' ? 'CPU' : 'GPU 优先')}</td>
          <td>{image?.loaded ? '已加载' : data?.deployed.image ? '待机，按需加载' : '模型下载中或未部署'}</td></tr>
        <tr><td className="p-2">中文语音 · Qwen3-TTS</td><td>GPU</td>
          <td>{voice?.suspended ? '为生图释放显存，语音排队' : voice?.busy ? '语音生成中' : voice?.loaded ? '已加载，空闲计时' : '待机，按需加载'}</td></tr>
      </tbody></table></div>
    {policy && <div className="rounded-lg p-4 space-y-3" style={{ border: '1px solid var(--color-border)' }}>
      <h3 className="font-medium">调度设置</h3>
      <label className="flex items-center justify-between gap-3 text-sm">生图设备
        <select style={inputStyle} value={policy.image_device} onChange={event => setPolicy({ ...policy, image_device: event.target.value })}>
          <option value="auto">自动：GPU 优先，资源不足用 CPU</option><option value="cuda">GPU：等待语音释放资源</option><option value="cpu">CPU：语音保持可用</option>
        </select></label>
      <label className="flex items-center justify-between gap-3 text-sm">GPU 生图时主助手
        <select style={inputStyle} value={policy.main_during_image} onChange={event => setPolicy({ ...policy, main_during_image: event.target.value })}>
          <option value="cpu">切换到 CPU 和内存，生图后恢复</option><option value="keep">保留当前设备</option>
        </select></label>
      {([['voice_idle_seconds', '语音空闲卸载（秒）'], ['writer_idle_seconds', '写作空闲卸载（秒）'],
        ['cpu_image_idle_seconds', 'CPU 生图空闲卸载（秒）'], ['voice_wait_seconds', '生图等待语音结束（秒）']] as const).map(([key, label]) =>
        <label key={key} className="flex items-center justify-between gap-3 text-sm">{label}
          <input type="number" min={0} max={1800} style={{ ...inputStyle, width: 100 }} value={policy[key]}
            onChange={event => setPolicy({ ...policy, [key]: Number(event.target.value) })} /></label>)}
      <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>0 表示尽快卸载。GPU 生图结束后立即卸载。主助手切到 CPU 会变慢，切换期间请求可能等待；同时将写作排队，避免内存拥挤。</p>
      <button className="px-4 py-2 rounded text-sm" style={{ background: 'var(--color-accent)', color: 'white' }} onClick={save} disabled={saving}>
        {saving ? '保存中…' : '保存设置'}</button> {message && <span className="text-sm">{message}</span>}
    </div>}
    <div>
      <h3 className="font-medium mb-2">当前子智能体任务</h3>
      {!data?.agents.some(agent => agent.status === 'running') && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>当前没有运行中的子智能体。</p>}
      {data?.agents.filter(agent => agent.status === 'running').map(agent => <div key={agent.id} className="text-sm py-2">
        {agent.name} · {agent.model || '主助手模型'} · {agent.activity || '运行中'}</div>)}
    </div>
    <div><h3 className="font-medium mb-2">调度任务记录</h3>
      {!data?.tasks.length && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>在子智能体中发起写作或生图后，任务会显示在这里。</p>}
      {data?.tasks.slice(0, 30).map(task => <div key={task.id} className="rounded-lg p-3 mb-2" style={{ background: 'var(--color-bg-secondary)' }}>
        <div className="flex justify-between text-sm"><span>{task.kind === 'image' ? '生图' : '写作'} · {task.model} · {task.device.toUpperCase()}</span>
          <span>{statusLabel[task.status] || task.status}{task.finished_at && task.started_at ? ` · ${(task.finished_at - task.started_at).toFixed(1)} 秒` : ''}</span></div>
        <p className="text-xs mt-1 break-words" style={{ color: 'var(--color-text-secondary)' }}>{task.description}</p>
        {task.reason && <p className="text-xs mt-1">{task.reason}</p>}
      </div>)}
    </div>
  </div>;
}
