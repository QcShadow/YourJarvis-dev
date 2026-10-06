import { useAppStore } from '../../lib/store';
import { authorityLabel, webProvenance } from '../../lib/web-provenance';
import type { ToolCallInfo } from '../../types';
import type { RetrievedSource } from '../../lib/web-provenance';

export function WebSources({ calls, content, inherited }: { calls?: ToolCallInfo[]; content: string; inherited?: RetrievedSource[] }) {
  const zh = useAppStore((s) => s.settings.interfaceLanguage === 'zh-CN');
  const evidence = webProvenance(calls, content, inherited);
  if (!evidence.searched) return null;
  return <div className="my-3 rounded-xl px-3 py-2 text-xs" data-i18n-ignore
    style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
    {evidence.failed && <p className="mb-2" role="status" style={{ color: 'var(--color-error)' }}>{zh ? '部分联网操作失败，请查看工具详情；下方回答不应当被视为已完整核验。' : 'Some retrieval failed. See tool details; the answer is not fully verified.'}</p>}
    {evidence.degraded && <p className="mb-2">{zh ? '主搜索服务不可用，已使用备用检索。' : 'Primary search was unavailable; fallback retrieval was used.'}</p>}
    {evidence.fallbackFailed && <p className="mb-2" role="status" style={{ color: 'var(--color-error)' }}>{zh ? '备用检索也未成功；请检查网络、DNS 或凭据。' : 'Fallback retrieval also failed; check network, DNS, or credentials.'}</p>}
    {evidence.carried && <p className="mb-2">{zh ? '包含先前对话的检索来源；沿用资料不代表本轮已重新查询。' : 'Includes sources from earlier turns; reusing them does not mean a new search ran.'}</p>}
    {evidence.missingRecords && <p className="mb-2">{zh ? '部分历史工具记录没有结构化来源，无法核对其中的链接。' : 'Some older tool records have no structured sources, so their links cannot be matched.'}</p>}
    {!!evidence.unmatched.size && <p className="mb-2" role="status" style={{ color: 'var(--color-error)' }}>{zh
      ? `回答中有 ${evidence.unmatched.size} 个链接无法与已记录来源对应，已标注。`
      : `${evidence.unmatched.size} answer link(s) could not be matched to recorded sources and are marked.`}</p>}
    <details>
      <summary className="cursor-pointer">{evidence.pending ? (zh ? '正在检索' : 'Searching') : (zh ? '实际检索来源' : 'Actually retrieved sources')} · {evidence.sources.length}</summary>
      <p className="my-2 opacity-70">{zh ? '这是检索记录，不代表每项事实均已核验。来源日期和查询时间可能不同。' : 'Retrieval records, not claim-by-claim fact checks. Publication dates may differ from query time.'}</p>
      <ol className="space-y-2 pl-4">
        {evidence.sources.map((source) => <li key={source.url}>
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="break-words underline" style={{ color: 'var(--color-accent)' }}>{source.title || source.url}</a>
          <span className="ml-2 opacity-70">{source.domain || new URL(source.url).hostname}</span>
          <span className="ml-2 rounded px-1 py-0.5 opacity-80" style={{ border: '1px solid var(--color-border)' }}>
            {authorityLabel(source.authority, zh)}
          </span>
          {source.retrieved_at && <div className="mt-1 opacity-60">{zh ? '查询：' : 'Queried: '}{new Date(source.retrieved_at).toLocaleString(zh ? 'zh-CN' : 'en-US')}</div>}
        </li>)}
      </ol>
    </details>
  </div>;
}
