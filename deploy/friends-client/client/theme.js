'use strict';
let preference = {palette:'mcu',dark:false};
try { preference = {...preference,...JSON.parse(localStorage.getItem('jarvis-link-appearance') || '{}')}; } catch {}
const options = window.jarvisPalettes;
const selector = document.getElementById('palette');
if (selector) for (const [key,palette] of Object.entries(options)) { const item=document.createElement('option');item.value=key;item.textContent=palette.label;selector.append(item); }
function apply() {
  const palette=options[preference.palette] || options.mcu;
  const [bg,surface,,text,secondary,accent]=preference.dark ? palette.dark : palette.light;
  const onAccent=preference.dark ? bg : '#ffffff';
  const values={'--bg':bg,'--surface':surface,'--text':text,'--muted':secondary,'--accent':accent,'--on-accent':onAccent};
  for (const [name,value] of Object.entries(values)) document.documentElement.style.setProperty(name,value);
  document.documentElement.style.colorScheme=preference.dark ? 'dark' : 'light';
  if(selector) selector.value=preference.palette;
  const toggle=document.getElementById('theme-toggle');if(toggle) toggle.textContent=preference.dark ? '浅色' : '深色';
  window.chrome?.webview?.postMessage({action:'theme',bg,surface,text,secondary,accent,onAccent});
}
function save(){localStorage.setItem('jarvis-link-appearance',JSON.stringify(preference));apply();}
selector?.addEventListener('change',()=>{preference.palette=selector.value;save();});
document.getElementById('theme-toggle')?.addEventListener('click',()=>{preference.dark=!preference.dark;save();});
apply();
