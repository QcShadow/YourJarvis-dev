'use strict';
const element = id => document.getElementById(id);
let token = '', history = [], controller = null, epoch = 0;
function error(message = '') { element('error').textContent = message; element('error').hidden = !message; }
function busy(active) { element('send').disabled = active; element('prompt').disabled = active; element('stop').hidden = !active; element('progress').textContent = active ? '等待主机处理…' : ''; }
function bubble(role, text) {
  element('empty')?.remove();
  const div = document.createElement('div'); div.className = 'message ' + role;
  const label = document.createElement('strong'); label.textContent = role === 'user' ? '你' : 'JARVIS';
  const content = document.createElement('span'); content.textContent = text;
  div.append(label, content); element('messages').append(div); div.scrollIntoView({ block: 'nearest' });
  return content;
}
function reset() { epoch++; controller?.abort(); controller = null; history = []; element('messages').replaceChildren(); element('prompt').value = ''; busy(false); error(); }
function disconnect() { reset(); token = ''; element('token').value = ''; element('chat').hidden = true; element('login').hidden = false; }
element('login-form').addEventListener('submit', async event => {
  event.preventDefault(); error(); element('connect').disabled = true;
  try {
    const candidate = element('token').value.trim();
    const response = await fetch('/api/friends/config', { headers: { Authorization: 'Bearer ' + candidate }, cache: 'no-store' });
    if (!response.ok) throw new Error(response.status === 401 ? '邀请令牌无效或已撤销。' : '主机暂时不可用。');
    const config = await response.json(); token = candidate; element('token').value = '';
    element('connection').textContent = config.member + ' · ' + config.model;
    element('chat').hidden = false; element('login').hidden = true; element('prompt').focus();
  } catch (e) { error(e.message); } finally { element('connect').disabled = false; }
});
element('chat-form').addEventListener('submit', async event => {
  event.preventDefault(); if (controller) return;
  const prompt = element('prompt').value.trim(); if (!prompt) return;
  const thisEpoch = epoch, active = new AbortController(); controller = active;
  let context = [...history, { role: 'user', content: prompt }].slice(-12);
  while (context.length > 1 && context.reduce((n, m) => n + m.content.length, 0) > 8000) context.shift();
  bubble('user', prompt); const answer = bubble('assistant', '');
  let reply = '', done = false; busy(true); error(); element('prompt').value = '';
  try {
    const response = await fetch('/api/friends/chat', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify({ messages: context }), signal: active.signal });
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(response.status === 401 ? '邀请已失效，请断开后重新连接。' : response.status === 429 ? '请求过于频繁，或上一条还在处理，请稍后重试。' : response.status === 503 ? '主机繁忙或排队超时，请稍后重试。' : typeof details.detail === 'string' ? details.detail : '请求失败，请新建对话后重试。');
    }
    element('progress').textContent = 'JARVIS 正在回复…';
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    try {
      while (true) {
        const next = await reader.read(); buffer += decoder.decode(next.value || new Uint8Array(), { stream: !next.done });
        let newline;
        while ((newline = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, newline).trimEnd(); buffer = buffer.slice(newline + 1);
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6); if (data === '[DONE]') { done = true; continue; }
          const item = JSON.parse(data); if (item.error) throw new Error(item.error);
          if (thisEpoch !== epoch) return;
          reply += item.content || ''; answer.textContent = reply; answer.scrollIntoView({ block: 'nearest' });
        }
        if (next.done) break;
      }
    } finally { reader.releaseLock(); }
    if (!done) throw new Error('连接中断，回复未完成。');
    if (!reply.trim()) throw new Error('模型返回了空回复，请稍后重试。');
    if (thisEpoch === epoch) history = [...context, { role: 'assistant', content: reply }];
  } catch (e) {
    if (thisEpoch === epoch) { error(e.name === 'AbortError' ? '已停止。' : e.message); if (!reply) answer.textContent = '未完成回复'; element('prompt').value = prompt; }
  } finally { if (thisEpoch === epoch) { controller = null; busy(false); element('prompt').focus(); } }
});
element('prompt').addEventListener('keydown', event => { if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); element('chat-form').requestSubmit(); } });
element('stop').addEventListener('click', () => controller?.abort());
element('new-chat').addEventListener('click', reset);
element('logout').addEventListener('click', disconnect);
