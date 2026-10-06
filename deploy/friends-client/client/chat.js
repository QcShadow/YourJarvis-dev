'use strict';
const element=id=>document.getElementById(id);
let history=[],activeId='',answer=null,reply='';
function error(message=''){element('error').textContent=message;element('error').hidden=!message;}
function busy(value){element('send').disabled=value;element('prompt').disabled=value;element('stop').hidden=!value;element('progress').textContent=value?'模型正在回复…':'';}
function bubble(role,text){element('empty')?.remove();const div=document.createElement('div');div.className='message '+role;const label=document.createElement('strong');label.textContent=role==='user'?'你':'JARVIS';const content=document.createElement('span');content.textContent=text;div.append(label,content);element('messages').append(div);div.scrollIntoView({block:'nearest'});return content;}
window.linkReply=item=>{if(item.id!==activeId)return;reply+=item.content||'';if(answer){answer.textContent=reply;answer.scrollIntoView({block:'nearest'});}if(item.done){if(item.error)error(item.error);else if(reply.trim())history.push({role:'assistant',content:reply});else error('模型返回了空回复，请稍后重试。');activeId='';busy(false);element('prompt').focus();}};
element('chat-form').addEventListener('submit',event=>{event.preventDefault();if(activeId)return;const prompt=element('prompt').value.trim();if(!prompt)return;error();let context=[...history,{role:'user',content:prompt}].slice(-12);while(context.length>1&&context.reduce((n,m)=>n+m.content.length,0)>8000)context.shift();history=context;activeId=crypto.randomUUID();reply='';bubble('user',prompt);answer=bubble('assistant','');element('prompt').value='';busy(true);window.chrome.webview.postMessage({action:'chat',id:activeId,messages:context});});
element('prompt').addEventListener('keydown',event=>{if(event.ctrlKey&&event.key==='Enter'){event.preventDefault();element('chat-form').requestSubmit();}});
element('stop').addEventListener('click',()=>window.chrome.webview.postMessage({action:'cancel'}));
element('new-chat').addEventListener('click',()=>{window.chrome.webview.postMessage({action:'cancel'});history=[];activeId='';reply='';answer=null;element('messages').replaceChildren();busy(false);error();});
