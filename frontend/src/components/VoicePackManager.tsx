import { useEffect, useState } from 'react';
import { useAppStore } from '../lib/store';
import { useTtsStore } from '../lib/tts';
import { responseLanguage } from '../lib/voice-settings';
import { deleteVoicePack, exportVoicePack, importVoicePack, renameVoicePack } from '../lib/voice-packs';
import type { VoiceProfile } from '../lib/voice-packs';
import { apiFetch } from '../lib/api';

export function VoicePackManager({ voices, onChanged }: { voices: VoiceProfile[]; onChanged: () => void }) {
  const settings = useAppStore((s) => s.settings);
  const update = useAppStore((s) => s.updateSettings);
  const zh = settings.interfaceLanguage === 'zh-CN';
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState('');
  const [transcript, setTranscript] = useState('');
  const [referenceLanguage, setReferenceLanguage] = useState('zh');
  const [speakerId, setSpeakerId] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [editing, setEditing] = useState('');
  const [editedName, setEditedName] = useState('');
  const [pendingDelete, setPendingDelete] = useState('');
  const [inputKey, setInputKey] = useState(0);
  const [create, setCreate] = useState(false);
  const [sampleUrl, setSampleUrl] = useState('');
  useEffect(() => () => { if (sampleUrl) URL.revokeObjectURL(sampleUrl); }, [sampleUrl]);
  const previewError = useTtsStore((s) => s.errorId?.startsWith('preview-') ? s.error : null);
  const style = { background: 'var(--color-bg-tertiary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
  const button = 'rounded-lg px-3 py-2 disabled:opacity-40';
  const hasAudio = files.some((f) => f.name.toLowerCase().endsWith('.wav'));
  const hasPiper = files.some((f) => f.name.toLowerCase().endsWith('.onnx'));
  const library = voices.filter((v) => v.user_owned);

  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  return <section className="mt-4 rounded-xl border p-4" style={{ borderColor: 'var(--color-border)' }} aria-label={zh ? '我的音色库' : 'My voice library'}>
    <h3 className="font-medium">{zh ? '我的音色库' : 'My voice library'}</h3>
    <p className="mt-2 text-xs opacity-70">{zh
      ? '导入 Piper ONNX＋JSON 或 .jvoice；也可上传纯净录音，用本地模型创建中英文音色。音色保存在本机，可导出 .jvoice 分享。'
      : 'Import Piper ONNX + JSON or .jvoice; create Chinese/English voices from clean recordings using the local model. Export voices as .jvoice to share.'}</p>
    <div className="mt-3 flex gap-2">
      <button type="button" className={button} style={style} disabled={busy} aria-pressed={!create} onClick={() => { setCreate(false); setFiles([]); setInputKey((k) => k + 1); }}>{zh ? '导入兼容音色' : 'Import compatible voice'}</button>
      <button type="button" className={button} style={style} disabled={busy} aria-pressed={create} onClick={() => { setCreate(true); setFiles([]); setInputKey((k) => k + 1); }}>{zh ? '从录音创建音色' : 'Create from recording'}</button>
    </div>
    <form className="mt-3 space-y-3" onSubmit={(event) => {
      event.preventDefault();
      void perform(async () => {
        const imported = await importVoicePack(files, name, transcript, referenceLanguage, speakerId, create);
        if (sampleUrl) URL.revokeObjectURL(sampleUrl);
        setSampleUrl('');
        if (create) {
          const response = await apiFetch(`/v1/speech/packs/${encodeURIComponent(imported.id)}/preview`);
          if (response.ok) setSampleUrl(URL.createObjectURL(await response.blob()));
        }
        setFiles([]); setName(''); setTranscript(''); setInputKey((key) => key + 1);
        setMessage(zh ? `已${create ? '生成并保存' : '导入'}：${imported.name}。${imported.installed ? '可以试听并选择使用。' : '请在上方安装对应引擎。'}`
          : `Imported: ${imported.name}. ${imported.installed ? 'Ready to preview.' : 'Engine installation required.'}`);
        onChanged();
      });
    }}>
      <label className="block">{zh ? '选择音色文件（可多选）' : 'Voice files (multiple allowed)'}
        <input key={inputKey} type="file" multiple accept={create ? '.wav,.txt' : '.wav,.txt,.onnx,.json,.jvoice,.zip'} disabled={busy}
          className="mt-1 block w-full text-xs" onChange={(e) => setFiles(Array.from(e.target.files || []))} />
      </label>
      <label className="block">{zh ? '音色名称（语音包可沿用内置名称）' : 'Name (optional for packaged voices)'}
        <input value={name} maxLength={80} disabled={busy} style={style} className="mt-1 w-full rounded-lg px-3 py-2"
          onChange={(e) => setName(e.target.value)} />
      </label>
      {hasAudio && <>
        <label className="block">{zh ? '录音对应文字（可选，填写后还原更准确）' : 'Reference transcript (optional; improves accuracy)'}
          <textarea value={transcript} maxLength={3000} rows={3} disabled={busy} style={style}
            className="mt-1 w-full rounded-lg px-3 py-2" onChange={(e) => setTranscript(e.target.value)} />
        </label>
        <p className="text-xs opacity-70">{zh ? '填写录音中实际说出的内容，也可同时选择 UTF-8 TXT。录音需为 1–30 秒、16 位 PCM WAV，建议 5–15 秒单人清晰讲话。'
          : 'Enter the exact words or include a UTF-8 TXT file. Use 1–30 seconds of 16-bit PCM WAV; 5–15 seconds of clear solo speech is recommended.'}</p>
        <label>{zh ? '录音语言' : 'Reference language'} <select value={referenceLanguage} disabled={busy} style={style}
          className="rounded-lg px-3 py-2" onChange={(e) => setReferenceLanguage(e.target.value)}>
          <option value="zh">中文</option><option value="en">English</option>
        </select></label>
      </>}
      {hasPiper && <label className="block">{zh ? '说话人编号（单音色模型填 0）' : 'Speaker ID (0 for single-speaker models)'}
        <input type="number" min={0} max={9999} step={1} value={speakerId} disabled={busy} style={style}
          className="ml-2 w-24 rounded-lg px-3 py-2" onChange={(e) => setSpeakerId(Number(e.target.value))} />
      </label>}
      <button type="submit" disabled={busy || !files.length || (create && !hasAudio)} style={style} className={button}>
        {busy ? zh ? '正在处理，请等待…' : 'Processing, please wait…' : create ? zh ? '生成样音并保存音色' : 'Generate preview and save voice' : zh ? '导入音色' : 'Import voice'}</button>
      {create && <p className="text-xs opacity-70">{zh ? '需先安装上方的录音创建音色模型。首次加载和 CPU 生成可能需要数分钟；生成失败不会留下半成品。只使用你有权使用的录音。' : 'Install the voice creation model above first. Initial loading and CPU generation may take minutes; failed creation leaves no partial voice. Use recordings you have permission to use.'}</p>}
    </form>
    {sampleUrl && <audio className="mt-3 w-full" controls src={sampleUrl} aria-label={zh ? '生成的样音' : 'Generated preview'} />}
    {message && <p role="status" className="mt-3 text-xs">{message}</p>}
    {error && <p role="alert" className="mt-3 text-xs">{error}</p>}
    {previewError && <p role="alert" className="mt-3 text-xs">{previewError}</p>}
    {!library.length && <p className="mt-4 text-xs opacity-70">{zh ? '还没有导入自定义音色。' : 'No custom voices imported yet.'}</p>}
    <ul className="mt-4 space-y-3">
      {library.map((voice) => {
        const chosen = voice.id === settings.voiceProfileZh || voice.id === settings.voiceProfileEn;
        const current = responseLanguage(settings);
        const language = (voice.languages.includes(current) ? current : voice.languages[0]) as 'zh' | 'en';
        return <li key={voice.id} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)' }}>
          {editing === voice.id ? <form className="flex flex-wrap gap-2" onSubmit={(e) => {
            e.preventDefault(); void perform(async () => { await renameVoicePack(voice.id, editedName); setEditing(''); onChanged(); });
          }}><input aria-label={zh ? '新名称' : 'New name'} value={editedName} maxLength={80} style={style}
            className="rounded-lg px-3 py-2" onChange={(e) => setEditedName(e.target.value)} />
            <button disabled={busy || !editedName.trim()} style={style} className={button}>{zh ? '保存名称' : 'Save name'}</button>
            <button type="button" onClick={() => setEditing('')} className={button}>{zh ? '取消' : 'Cancel'}</button></form>
            : <div className="font-medium">{voice.name}</div>}
          <p className="mt-1 text-xs opacity-70">{voice.kind === 'reference' ? zh ? '参考录音' : 'Reference voice' : 'Piper'} · {voice.languages.join('/')}
            {' · '}{voice.installed ? zh ? '已导入，可试听' : 'Imported, available to preview' : zh ? '缺少引擎或文件' : 'Engine or assets missing'}
            {chosen ? zh ? ' · 已选择' : ' · Selected' : ''}</p>
          {voice.note && <p className="mt-1 text-xs opacity-70">{voice.note}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" disabled={busy || !voice.installed} style={style} className={button}
              onClick={() => void useTtsStore.getState().speak(`preview-${voice.id}`, language === 'zh'
                ? '我在。系统运行正常，我们可以开始了。' : "I'm here. Systems are operational.",
              { voiceProfile: voice.id, outputLanguage: language, characterId: settings.characterId })}>{zh ? '试听' : 'Preview'}</button>
            <button type="button" disabled={busy || !voice.installed} style={style} className={button} onClick={() => {
              useTtsStore.getState().stop();
              update({ outputLanguage: language, voiceOutputEnabled: true,
                ...(language === 'zh' ? { voiceProfileZh: voice.id } : { voiceProfileEn: voice.id }) });
            }}>{zh ? `用于${language === 'zh' ? '中文' : '英文'}朗读` : `Use for ${language} speech`}</button>
            <button type="button" disabled={busy} style={style} className={button} onClick={() => { setEditing(voice.id); setEditedName(voice.name); }}>
              {zh ? '重命名' : 'Rename'}</button>
            <button type="button" disabled={busy} style={style} className={button} onClick={() => void perform(async () => {
              const blob = await exportVoicePack(voice.id); const url = URL.createObjectURL(blob);
              const link = document.createElement('a'); link.href = url; link.download = `${voice.id}.jvoice`;
              document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
            })}>{zh ? '导出' : 'Export'}</button>
            <button type="button" disabled={busy || chosen} style={style} className={button}
              title={chosen ? zh ? '请先切换已选择的音色' : 'Switch selected voice first' : undefined}
              onClick={() => setPendingDelete(voice.id)}>{zh ? '删除' : 'Delete'}</button>
          </div>
          {pendingDelete === voice.id && <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs">{zh ? '删除本机保存的这个音色？' : 'Delete this voice from the local library?'}</span>
            <button type="button" disabled={busy} style={style} className={button} onClick={() => void perform(async () => {
              useTtsStore.getState().stop(); await deleteVoicePack(voice.id); setPendingDelete(''); onChanged();
            })}>{zh ? '确认删除' : 'Confirm delete'}</button>
            <button type="button" className={button} onClick={() => setPendingDelete('')}>{zh ? '取消' : 'Cancel'}</button>
          </div>}
        </li>;
      })}
    </ul>
  </section>;
}
