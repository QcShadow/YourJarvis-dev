// Inspect our own native WebView2 client. Never attach to the private desktop.
import { readFile, writeFile } from 'node:fs/promises';

const mode = process.argv[2] || 'local';
let pages;
for(let i=0;i<80;i++) {
  try { pages=await(await fetch('http://127.0.0.1:9247/json/list')).json();if(pages.some(p=>p.type==='page'))break; } catch {}
  await new Promise(resolve=>setTimeout(resolve,250));
}
if(!pages)throw new Error('Native debug endpoint did not start');
const page = pages.find(item => item.type === 'page');
if (!page) throw new Error('Friends WebView2 page not available');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once:true}); socket.addEventListener('error', reject, {once:true}); });
let sequence = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const response = JSON.parse(event.data), request = pending.get(response.id);
  if (!request) return;
  pending.delete(response.id);
  response.error ? request.reject(new Error(response.error.message)) : request.resolve(response.result);
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; pending.set(id, {resolve,reject}); socket.send(JSON.stringify({id,method,params})); });
let blockedExternalRequests = 0;
socket.addEventListener('message', event => {
  const value = JSON.parse(event.data);
  if (value.method !== 'Fetch.requestPaused') return;
  const allowed = value.params.request.url.startsWith('https://jarvis-link.local/');
  if (!allowed) blockedExternalRequests++;
  send(allowed ? 'Fetch.continueRequest' : 'Fetch.failRequest', allowed
    ? {requestId:value.params.requestId}
    : {requestId:value.params.requestId,errorReason:'InternetDisconnected'}).catch(()=>{});
});
async function evaluate(expression) {
  const response = await send('Runtime.evaluate', {expression,awaitPromise:true,returnByValue:true});
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result?.value;
}
async function wait(expression, seconds = 40) {
  for (let i = 0; i < seconds * 5; i++) {
    if (await evaluate(expression)) return;
    if (i % 100 === 99) console.log(await evaluate('document.getElementById("log")?.textContent.slice(-200) || location.origin'));
    await new Promise(resolve => setTimeout(resolve,200));
  }
  throw new Error('Timed out: ' + expression + ' / ' + await evaluate('document.body.innerText.slice(-1200)'));
}
async function screenshot(name) {
  const shot = await send('Page.captureScreenshot', {format:'png'});
  await writeFile('D:/Jarvis/logs/' + name, Buffer.from(shot.data,'base64'));
}
try {
  await send('Runtime.enable'); await send('Page.enable');
  if (mode === 'local') {
    await send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
    await wait('!!document.getElementById("local")');
    await screenshot('friends-client-home.png');
    await evaluate('document.getElementById("address").value="http://example.invalid";document.getElementById("token").value="jf_test";document.getElementById("remote-form").requestSubmit()');
    await wait('!document.getElementById("error").hidden');
    if (!(await evaluate('document.getElementById("error").textContent.includes("HTTPS") && !document.getElementById("local").disabled && document.getElementById("token").value === ""'))) throw new Error('Remote validation did not recover');
    await evaluate('document.getElementById("local").click()');
    await wait('location.pathname === "/chat.html" && !!document.getElementById("chat-form")', 40);
    const origin = await evaluate('location.origin');
    if (origin !== 'https://jarvis-link.local') throw new Error('Local client did not use its offline page');
  } else {
    await send('Page.navigate', {url:'https://jarvis-link.local/home.html'});
    await wait('!!document.getElementById("remote-form")');
    const token = (await readFile('D:/Jarvis/cache/friends-client-host-qa/qa-token.txt','utf8')).trim();
    await evaluate('document.getElementById("address").value="http://127.0.0.1:8003";document.getElementById("token").value="jf_invalid";document.getElementById("remote-form").requestSubmit()');
    await wait('!document.getElementById("error").hidden');
    if (!(await evaluate('document.getElementById("error").textContent.includes("无效")'))) throw new Error('Invalid host token was not rejected');
    await evaluate(`document.getElementById("token").value=${JSON.stringify(token)};document.getElementById("remote-form").requestSubmit()`);
    await wait('location.port === "8003" && !document.getElementById("chat")?.hidden');
  }
  await evaluate('document.getElementById("prompt").value="你好，请用一句话介绍自己。";document.getElementById("chat-form").requestSubmit()');
  await wait('!document.getElementById("send").disabled && !!document.querySelector(".message.assistant span")?.textContent', 60);
  const result = await evaluate('({origin:location.origin,reply:document.querySelector(".message.assistant span").textContent,error:document.getElementById("error").textContent,tokenPersisted:Object.values(localStorage).some(v=>v.includes("jf_")),overflow:document.documentElement.scrollWidth>innerWidth})');
  if (result.error || !result.reply.trim()) throw new Error(JSON.stringify(result));
  if (result.tokenPersisted || result.overflow) throw new Error('Token persistence or horizontal overflow');
  result.browser = (await send('Browser.getVersion')).product;
  result.externalRequestsBlocked = mode === 'local';
  result.blockedExternalRequests = blockedExternalRequests;
  await screenshot(`friends-client-${mode}-chat.png`);
  await writeFile(`D:/Jarvis/logs/friends-client-${mode}-qa.json`,JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
} finally { await send('Fetch.disable').catch(()=>{}); socket.close(); }
