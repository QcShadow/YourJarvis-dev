import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import { useAppStore } from '../lib/store';
import { useTtsStore } from '../lib/tts';
import { characterPreset, responseLanguage, selectedVoiceProfile } from '../lib/voice-settings';
import type { VoiceProfile } from '../lib/voice-packs';
import { VoicePackManager } from './VoicePackManager';

export function VoicePersonaSettings() {
  const settings = useAppStore((s) => s.settings);
  const update = useAppStore((s) => s.updateSettings);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const zh = settings.interfaceLanguage === 'zh-CN';
  const language = responseLanguage(settings);
  const selected = selectedVoiceProfile(settings);
  useEffect(() => {
    let disposed = false;
    apiFetch('/v1/speech/profiles').then(async (r) => {
      if (!r.ok) throw new Error(zh ? '音色列表暂时不可用' : 'Voice catalog unavailable');
      const data = await r.json();
      if (!disposed) { setVoices(data.voices); setError(''); }
    }).catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [zh, revision]);
  const options = voices.filter((v) => v.languages.includes(language) && v.characters.includes(settings.characterId));
  const active = voices.find((v) => v.id === selected);
  const style = { background: 'var(--color-bg-tertiary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
  const row = 'flex flex-wrap items-center justify-between gap-3 py-3';
  return <div className="text-sm" data-i18n-ignore>
    <div className={row}>
      <label htmlFor="character-profile">{zh ? '角色 / 人设' : 'Character / persona'}</label>
      <select id="character-profile" value={settings.characterId} style={style} className="rounded-lg px-3 py-2"
        onChange={(e) => { useTtsStore.getState().stop(); update(characterPreset(e.target.value as typeof settings.characterId)); }}>
        <option value="jarvis-local">{zh ? '贾维斯 · 本地助手' : 'Jarvis · Local assistant'}</option>
        <option value="mcu-jarvis">MCU Jarvis · English</option>
      </select>
    </div>
    <p className="text-xs opacity-70">{settings.characterId === 'mcu-jarvis'
      ? zh ? '电影风格预设：英式表达、沉稳精确、克制幽默。选择时绑定英文 Jarvis 音源和英文输出；不是官方演员录音。你仍可独立设置识别语言。' : 'Movie-inspired preset: measured British English, precise results and restrained dry wit. Binds English Jarvis voice and English replies; not an official actor recording. Recognition language remains independent.'
      : zh ? '冷静、直接、自然简短。不把用户当成 Tony，不编造执行结果。' : 'Calm, practical, naturally concise. No fictional capabilities or invented task completion.'}</p>
    {voices.some((v) => v.id === 'jarvis-multilingual' && v.installed) && <button type="button"
      style={style} className="mt-3 rounded-lg px-3 py-2"
      onClick={() => {
        useTtsStore.getState().stop();
        update({ ...characterPreset('mcu-jarvis'), outputLanguage: 'zh',
          voiceProfileZh: 'jarvis-multilingual', voiceOutputEnabled: true });
      }}>{zh ? '使用中文跨语言贾维斯' : 'Use Mandarin cross-language Jarvis'}</button>}
    <div className={row}>
      <label htmlFor="response-language">{zh ? '回答与朗读语言' : 'Reply and speech language'}</label>
      <select id="response-language" value={settings.outputLanguage} style={style} className="rounded-lg px-3 py-2"
        onChange={(e) => { useTtsStore.getState().stop(); update({ outputLanguage: e.target.value as typeof settings.outputLanguage }); }}>
        <option value="recognition">{zh ? '跟随识别设置（不是跟随句子）' : 'Follow recognition setting, not each sentence'}</option>
        <option value="zh">简体中文</option><option value="en">English</option>
      </select>
    </div>
    <div className={row}>
      <label htmlFor="voice-profile">{zh ? '音色 / 音源' : 'Voice / source'}</label>
      <select id="voice-profile" value={selected} style={style} className="max-w-full rounded-lg px-3 py-2"
        onChange={(e) => { useTtsStore.getState().stop(); update(language === 'zh' ? { voiceProfileZh: e.target.value } : { voiceProfileEn: e.target.value }); }}>
        {options.map((v) => <option key={v.id} value={v.id} disabled={!v.installed}>
          {v.name} · {v.languages.join('/')} {v.experimental ? zh ? '（实验）' : '(experimental)' : ''}{!v.installed ? zh ? ' · 未安装' : ' · not installed' : ''}
        </option>)}
      </select>
      <button type="button" style={style} className="rounded-lg px-3 py-2" disabled={!active?.installed}
        onClick={() => void useTtsStore.getState().speak('voice-preview', language === 'zh'
          ? '我在。系统运行正常，我们可以开始了。' : "I'm here. Systems are operational. What shall we work on?")}>{zh ? '试听所选音色' : 'Preview selected voice'}</button>
    </div>
    <p className="text-xs opacity-70">{zh ? '音源按角色和输出语言筛选；英文专用音源不会因中文句子中的英文单词而自动启用。跨语言实验音源需单独选择，可能明显更慢。' : 'Voices are filtered by persona and reply language. English words in Chinese replies never switch the voice. Cross-language synthesis is explicitly opt-in and can be slower.'}</p>
    {active && <p className="mt-2 text-xs opacity-70">{zh ? '当前：' : 'Active: '}{active.backend} / {active.name} · {language}</p>}
    {active?.note && <p className="mt-2 text-xs opacity-70">{active.note}</p>}
    {error && <p role="alert" className="mt-2 text-xs">{error}</p>}
    <VoicePackManager voices={voices} onChanged={() => setRevision((value) => value + 1)} />
    <div className={row}>
      <label htmlFor="speech-pause">{zh ? '说完后的等待' : 'End-of-speech pause'} · {(settings.speechPauseMs / 1000).toFixed(1)}s</label>
      <input id="speech-pause" type="range" min={700} max={2500} step={100} value={settings.speechPauseMs}
        onChange={(e) => update({ speechPauseMs: Number(e.target.value) })} />
    </div>
    <p className="text-xs opacity-70">{zh ? '这是基础等待时间；如果一句话里有较长停顿或持续讲话，系统会适当延长，不会只按固定秒数截断。默认 1.8 秒，短指令仍按基础等待快速响应。' : 'A baseline, not a rigid cutoff: internal pauses and longer speech extend the wait modestly. The 1.8 second default still keeps short commands responsive.'}</p>
    <div className={row}>
      <label htmlFor="voice-idle">{zh ? '无输入后需要重新唤醒' : 'Idle time before wake is required'}</label>
      <select id="voice-idle" value={settings.voiceIdleSeconds} style={style} className="rounded-lg px-3 py-2"
        onChange={(e) => update({ voiceIdleSeconds: Number(e.target.value) })}>
        {[10, 20, 30, 60, 120, 300].map((seconds) => <option key={seconds} value={seconds}>{seconds} {zh ? '秒' : 'seconds'}</option>)}
      </select>
    </div>
    <div className={row}>
      <label htmlFor="interrupt-words">{zh ? '打断词（逗号分隔）' : 'Interrupt phrases (comma-separated)'}</label>
      <input id="interrupt-words" defaultValue={settings.interruptWords.join(', ')} key={settings.interruptWords.join(',')}
        style={style} className="w-full rounded-lg px-3 py-2" maxLength={650}
        onBlur={(e) => update({ interruptWords: [...new Set(e.target.value.split(/[,，\n]/).map((word) => word.trim()).filter(Boolean))].slice(0, 16).map((word) => word.slice(0, 40)) })} />
    </div>
    <p className="text-xs opacity-70">{zh ? '生成或朗读时说“停一下”可打断，也可接着说新的要求。空列表关闭打断词；超时后必须重新说唤醒词。已开始的系统操作不会被强行终止。外放时建议使用耳机，减少回声误识别。' : 'Say an interrupt phrase while generating or speaking; optionally follow with a revised request. An empty list disables phrase controls. After idle timeout, wake again. Already-started system operations drain safely. Headphones help avoid speaker echo.'}</p>
  </div>;
}
