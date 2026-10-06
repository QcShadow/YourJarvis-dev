import { useEffect, useMemo, useState } from 'react';
import { BarChart3 } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { fetchModelUsage, type ModelUsageStat } from '../../lib/api';

interface Row {
  model: string;
  calls: number;
  input: number;
  output: number;
  estimated: boolean;
}

export function ModelUsage() {
  const conversations = useAppStore((state) => state.conversations);
  const selectedModel = useAppStore((state) => state.selectedModel);
  const zh = useAppStore((state) => state.settings.interfaceLanguage) === 'zh-CN';
  const [serverRows, setServerRows] = useState<ModelUsageStat[] | null>(null);
  useEffect(() => {
    let active = true;
    const refresh = () => { void fetchModelUsage().then((rows) => { if (active) setServerRows(rows); }).catch(() => {}); };
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  const rows = useMemo(() => {
    const counts = new Map<string, Row>();
    for (const conversation of conversations) {
      for (const message of conversation.messages) {
        if (message.role !== 'assistant' || !message.content) continue;
        const model = message.telemetry?.model_id || conversation.model || 'Unknown';
        const row = counts.get(model) ?? { model, calls: 0, input: 0, output: 0, estimated: false };
        row.calls++;
        row.input += message.usage?.prompt_tokens ?? 0;
        row.output += message.usage?.completion_tokens ?? 0;
        row.estimated ||= !!message.usage?.estimated || !message.usage;
        counts.set(model, row);
      }
    }
    return [...counts.values()].sort((a, b) => b.calls - a.calls || b.output - a.output);
  }, [conversations]);
  const usingServer = !!serverRows?.length;
  const ranked = usingServer ? serverRows.map((row) => ({
    model: row.model_id,
    calls: row.call_count,
    input: row.prompt_tokens,
    output: row.completion_tokens,
    estimated: true,
  })).sort((a, b) => b.calls - a.calls || b.output - a.output) : rows;
  const maxCalls = Math.max(1, ...ranked.map((row) => row.calls));

  return <section className="hud-panel p-6 mb-4">
    <h2 className="hud-label flex items-center gap-2 mb-2"><BarChart3 size={13} />{zh ? '模型使用排行' : 'Model usage ranking'}</h2>
    <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
      {usingServer ? zh ? '本机记录：包含网页、命令行及智能体推理；不含路由判断。≈ 表示流式 token 数可能为估算。' : 'Local usage including GUI, CLI and agents; routing calls excluded. ≈ denotes possible streaming estimates.'
        : zh ? '仅统计本浏览器保存的对话；不含命令行或其他设备。' : 'Browser chat history only; CLI and other devices excluded.'}
    </p>
    <p className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>{zh ? '当前手动模型' : 'Selected model'}: {selectedModel || '—'}</p>
    {ranked.length === 0 ? <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>{zh ? '暂无对话数据' : 'No chat data yet'}</p> :
      <div className="space-y-3">
        {ranked.map((row, index) => <div key={row.model}>
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="truncate" style={{ color: 'var(--color-text)' }}>#{index + 1} {row.model}</span>
            <span className="shrink-0 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              {row.calls} {zh ? '次' : 'calls'} · {zh ? '输入' : 'in'} {row.input.toLocaleString()} · {zh ? '输出' : 'out'} {row.estimated ? '≈' : ''}{row.output.toLocaleString()} tokens
            </span>
          </div>
          <div className="h-1.5 rounded-full mt-1" style={{ background: 'var(--color-bg-tertiary)' }}>
            <div className="h-full rounded-full" style={{ width: `${row.calls / maxCalls * 100}%`, background: 'var(--color-accent)' }} />
          </div>
        </div>)}
      </div>}
  </section>;
}
