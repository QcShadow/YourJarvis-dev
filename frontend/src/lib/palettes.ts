/** Original palettes inspired by familiar visual styles, not official themes. */
export const palettes = {
  codex: { label: 'Codex', light: ['#fafafa', '#ffffff', '#f1f1f1', '#161616', '#565656', '#087858'], dark: ['#111111', '#191919', '#242424', '#f4f4f4', '#aaaaaa', '#65d6ad'] },
  claude: { label: 'Claude', light: ['#f6f3ed', '#fffcf7', '#ece6dc', '#302e2a', '#6b6258', '#a8452c'], dark: ['#211f1c', '#2c2925', '#38332d', '#f5eee5', '#b6ab9c', '#efb08d'] },
  deepseek: { label: 'DeepSeek', light: ['#f4f7ff', '#ffffff', '#e6ecfc', '#182340', '#526381', '#295acb'], dark: ['#0e1527', '#161f36', '#24304b', '#ecf1ff', '#a3b3d5', '#88adff'] },
  midnight: { label: '深色 / Midnight', light: ['#eceef2', '#ffffff', '#dde1e9', '#202633', '#5c6576', '#5148bd'], dark: ['#13151c', '#1b1e28', '#292d3b', '#eef0f7', '#abb0c2', '#b5afff'] },
  anime: { label: '二次元 / Pastel', light: ['#fff5fa', '#fffafd', '#f5e1ef', '#472d45', '#7c5975', '#ab337f'], dark: ['#251b30', '#31243f', '#483154', '#ffeafa', '#d3afce', '#f5a9de'] },
  hacker: { label: '黑客 / Terminal', light: ['#f0f6f1', '#fafffb', '#dceadf', '#102b18', '#486c51', '#12632e'], dark: ['#080d09', '#0f1911', '#1b2c1f', '#c7f7d1', '#88b990', '#76ed95'] },
  mcu: { label: 'MCU Jarvis · HUD', light: ['#f2f8fc', '#ffffff', '#dcecf5', '#15314a', '#4c6b80', '#087b99'], dark: ['#070d16', '#0c1726', '#172c40', '#e2f6ff', '#93bacb', '#60ddff'] },
} as const;

export type ColorScheme = keyof typeof palettes;

export function applyPalette(root: HTMLElement, scheme: ColorScheme, dark: boolean) {
  const palette = palettes[scheme] || palettes.mcu;
  const [bg, surface, muted, text, secondary, accent] = dark ? palette.dark : palette.light;
  const values: Record<string, string> = {
    '--color-bg': bg, '--color-bg-secondary': surface, '--color-bg-tertiary': muted,
    '--color-surface': surface, '--color-sidebar': surface, '--color-text': text,
    '--color-text-secondary': secondary, '--color-text-tertiary': secondary,
    '--color-accent': accent, '--color-accent-hover': accent,
    '--color-accent-subtle': `color-mix(in srgb, ${accent} 10%, transparent)`,
    '--color-accent-glow': `color-mix(in srgb, ${accent} 24%, transparent)`,
    '--color-border': `color-mix(in srgb, ${text} 14%, transparent)`,
    '--color-border-subtle': `color-mix(in srgb, ${text} 7%, transparent)`,
    '--color-code-bg': muted, '--color-input-bg': surface, '--color-input-border': `color-mix(in srgb, ${accent} 30%, transparent)`,
    '--color-user-bubble': `color-mix(in srgb, ${accent} 12%, ${surface})`, '--color-user-bubble-text': text,
    '--color-disabled-bg': muted, '--color-on-accent': dark ? bg : '#ffffff', '--color-text-inverse': bg,
    '--background': bg, '--foreground': text, '--card': surface, '--card-foreground': text,
    '--popover': surface, '--popover-foreground': text, '--secondary': muted, '--secondary-foreground': text,
    '--muted': muted, '--muted-foreground': secondary, '--accent': muted, '--accent-foreground': text,
    '--border': `color-mix(in srgb, ${text} 14%, transparent)`, '--input': muted, '--ring': accent,
    '--sidebar': surface, '--sidebar-foreground': text, '--sidebar-accent': muted, '--sidebar-accent-foreground': text,
  };
  for (const [key, value] of Object.entries(values)) root.style.setProperty(key, value);
  root.dataset.palette = scheme;
  root.style.colorScheme = dark ? 'dark' : 'light';
}
