'use strict';
const get = id => document.getElementById(id);
const bridge = window.chrome?.webview;
function busy(value) { get('local').disabled = value; get('remote').disabled = value; get('progress').hidden = !value; }
function error(message) { get('error').textContent = message || ''; get('error').hidden = !message; }
window.friendStatus = (message, failed = false) => {
  if (failed) { error(message); busy(false); return; }
  get('status').textContent = '正在准备，请稍候…';
  get('log').textContent = (get('log').textContent + '\n' + message).split('\n').slice(-40).join('\n');
  get('log').scrollTop = get('log').scrollHeight;
};
window.friendAddress = address => { get('address').value = address || ''; };
function submit(payload) {
  error('');
  if (!bridge) { error('请使用 JARVIS-Link.exe 打开应用，以启动本地模型或连接主机。'); return; }
  get('log').textContent = ''; busy(true); bridge.postMessage(payload);
}
get('local').addEventListener('click', () => submit({ action: 'local' }));
get('remote-form').addEventListener('submit', event => {
  event.preventDefault();
  const address = get('address').value.trim(), token = get('token').value.trim();
  if (!address || !token) return;
  get('token').value = ''; submit({ action: 'remote', address, token });
});
bridge?.postMessage({ action: 'ready' });
