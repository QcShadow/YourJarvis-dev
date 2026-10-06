import { useAppStore } from '../lib/store';
import { palettes, type ColorScheme } from '../lib/palettes';

export function PaletteSettings() {
  const settings = useAppStore((s) => s.settings);
  const update = useAppStore((s) => s.updateSettings);
  const zh = settings.interfaceLanguage === 'zh-CN';
  return <div className="py-3" data-i18n-ignore>
    <h3 className="mb-3 text-sm">{zh ? '配色方案' : 'Colour palette'}</h3>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {Object.entries(palettes).map(([key, p]) => {
        const selected = settings.colorScheme === key;
        const colours = settings.theme === 'light' ? p.light : p.dark;
        return <button key={key} aria-pressed={selected} onClick={() => update({ colorScheme: key as ColorScheme })}
          className="rounded-xl p-3 text-left text-xs transition-colors" style={{ background: colours[0], color: colours[3],
            border: `2px solid ${selected ? colours[5] : 'var(--color-border)'}` }}>
          <div className="mb-2 flex gap-1.5" aria-hidden="true">{[colours[1], colours[2], colours[5]].map((c) => <span key={c} className="h-3 w-3 rounded-full" style={{ background: c, border: `1px solid ${colours[4]}` }} />)}</div>
          {p.label}{selected ? ' ✓' : ''}
        </button>;
      })}
    </div>
    <p className="mt-2 text-xs opacity-70">{zh ? '原创风格配色，非品牌官方主题。每套配色都支持浅色、深色与跟随系统；不会改变角色或音色。' : 'Original style-inspired palettes, not official brand themes. Each supports light/dark/system independently of persona and voice.'}</p>
  </div>;
}
