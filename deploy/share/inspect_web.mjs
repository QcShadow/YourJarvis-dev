// Developer-only CDP smoke test. Uses its own headless browser profile.
import { readFile, writeFile } from 'node:fs/promises';

const base = 'http://127.0.0.1:9245';
const qaToken = (await readFile('D:/Jarvis/cache/distribution-qa-friends/qa-token.txt', 'utf8')).trim();
const screenshotRoot = 'D:/Jarvis/logs';
async function inspect(url, run, screenshot) {
  const page = await (await fetch(base + '/json/new?' + encodeURIComponent(url), { method: 'PUT' })).json();
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let counter = 0; const pending = new Map(); const errors = [];
  socket.addEventListener('message', event => {
    const value = JSON.parse(event.data);
    if (value.method === 'Runtime.exceptionThrown') errors.push(value.params.exceptionDetails.text);
    const item = pending.get(value.id); if (!item) return; pending.delete(value.id);
    value.error ? item.reject(new Error(value.error.message)) : item.resolve(value.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++counter; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result?.value;
  };
  const wait = async expression => {
    for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 100)); }
    throw new Error('Timed out: ' + expression);
  };
  try {
    await send('Runtime.enable'); await send('Page.enable');
    await wait('document.readyState === "complete"');
    const result = await run({ evaluate, wait });
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    await writeFile(`${screenshotRoot}/${screenshot}`, Buffer.from(shot.data, 'base64'));
    if (errors.length) throw new Error(errors.join('\n'));
    return result;
  } finally { socket.close(); await fetch(base + '/json/close/' + page.id); }
}
const friends = await inspect('http://127.0.0.1:8003/', async ({ evaluate, wait }) => {
  await wait('!!document.getElementById("login-form")');
  await evaluate(`document.getElementById('token').value = ${JSON.stringify(qaToken)}; document.getElementById('login-form').requestSubmit()`);
  await wait('!document.getElementById("chat").hidden');
  await evaluate("document.getElementById('prompt').value = '你好，请用一句话介绍自己。'; document.getElementById('chat-form').requestSubmit()");
  await wait('!document.getElementById("send").disabled && !!document.querySelector(".message.assistant span")?.textContent');
  const result = await evaluate('({reply: document.querySelector(".message.assistant span").textContent, error: document.getElementById("error").textContent, storedToken: localStorage.length})');
  if (result.error) throw new Error(result.error);
  return result;
}, 'friends-web-qa.png');
const settings = await inspect('http://127.0.0.1:8004/settings', async ({ evaluate, wait }) => {
  await wait('document.body.innerText.includes("模型与首次配置预设")');
  await wait('document.querySelector("select[aria-label=模型方案]")?.value === "custom-local"');
  await evaluate('document.querySelector("select[aria-label=模型方案]").closest("section").scrollIntoView({block:"start"})');
  return evaluate('({presetVisible: document.body.innerText.includes("轻量中文"), savedSettings: JSON.parse(localStorage.getItem("openjarvis-settings")), overflow: document.documentElement.scrollWidth > innerWidth})');
}, 'deployment-settings-qa.png');
await writeFile(`${screenshotRoot}/distribution-web-qa.json`, JSON.stringify({ friends, settings }, null, 2));
console.log(JSON.stringify({ friends, settings }, null, 2));
