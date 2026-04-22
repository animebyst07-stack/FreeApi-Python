/* views/support.js — модуль раздела «Поддержка» (шаг 0.5.13).
   Перенесён из inline-блока static/index.html (~3540..3745).

   ВНЕШНИЕ ЗАВИСИМОСТИ (берутся из window.* — определены либо inline, либо в других ESM):
     - window.api                — XHR-обёртка (core/api.js)
     - window.showToast          — тосты (ui/toast.js)
     - window.customConfirm      — confirm-модалка (ui/modal.js)
     - window.parseTgMarkdown    — inline TG-markdown (остаётся inline до отдельного шага)
     - window.autoResizeTextarea — inline (остаётся inline)
     - window.user               — текущий юзер (inline state, ещё не вынесен)

   Все публичные имена дублируются на window.* для совместимости с inline
   onclick-хендлерами и view-роутером (ui/view.js → window.initSupportView()). */

var _supportPending = false;
var _supportImageBase64 = '';
var _supportImageName = '';

function getApi()   { return window.api; }
function getUser()  { return window.user; }
function toast(m, t){ if (window.showToast) window.showToast(m, t); }

function initSupportView(){
  if(!getUser()){
    document.getElementById('supportRequireAuth').style.display='';
    document.getElementById('supportChatWrap').style.display='none';
    return;
  }
  document.getElementById('supportRequireAuth').style.display='none';
  document.getElementById('supportChatWrap').style.display='';
  document.getElementById('supportCloseBtn').style.display='none';
  loadSupportHistory();
  var ta=document.getElementById('supportInput');
  if(ta && !ta._resizeInit){
    ta._resizeInit=true;
    ta.style.overflow='hidden';
    ta.addEventListener('input',function(){
      if(window.autoResizeTextarea) window.autoResizeTextarea(this,130);
    });
    ta.addEventListener('keydown',function(e){
      if(e.key==='Enter' && !e.shiftKey && !_supportPending){
        e.preventDefault();
        sendSupportMessage();
      }
    });
  }
}

function loadSupportHistory(){
  var api=getApi(); if(!api) return;
  api('/api/support/chat').then(function(d){
    var msgs=document.getElementById('supportMessages');
    var empty=document.getElementById('supportEmptyState');
    Array.from(msgs.querySelectorAll('.chat-msg,.chat-thinking')).forEach(function(el){el.remove();});
    if(!d.messages || !d.messages.length){
      if(empty) empty.style.display='flex';
      document.getElementById('supportCloseBtn').style.display='none';
      return;
    }
    if(empty) empty.style.display='none';
    document.getElementById('supportCloseBtn').style.display='';
    d.messages.forEach(function(m){
      appendSupportMsg(m.role, m.content, m.image_data);
    });
    if(d.chat && d.chat.status==='closed'){
      var status=document.getElementById('supportChatStatus');
      if(status) status.textContent='Диалог завершён';
      document.getElementById('supportCloseBtn').style.display='none';
      var _ncb=document.getElementById('supportNewChatBtn');
      if(_ncb) _ncb.style.display='';
      document.getElementById('supportInput').disabled=true;
      document.getElementById('supportSendBtn').disabled=true;
    }
  }).catch(function(){});
}

function appendSupportMsg(role, content, imageSrc){
  var msgs=document.getElementById('supportMessages');
  var empty=document.getElementById('supportEmptyState');
  if(empty) empty.style.display='none';
  var div=document.createElement('div');
  div.className='chat-msg '+(role==='user'?'user':'assistant');
  var bubble=document.createElement('div');
  bubble.className='chat-bubble';
  if(role!=='user'){
    if(imageSrc){
      var img=document.createElement('img');
      img.src=imageSrc;
      img.style.cssText='max-width:180px;max-height:140px;border-radius:8px;display:block;margin-bottom:8px;border:1px solid #1e1e1e';
      bubble.appendChild(img);
    }
    var md = (window.parseTgMarkdown ? window.parseTgMarkdown(content||'') : (content||''));
    bubble.innerHTML += (imageSrc?'':'') + md;
  } else {
    if(imageSrc){
      var img=document.createElement('img');
      img.src=imageSrc;
      img.style.cssText='max-width:180px;max-height:140px;border-radius:8px;display:block;margin-bottom:8px;border:1px solid #1e1e1e';
      bubble.appendChild(img);
    }
    var span=document.createElement('span');
    span.textContent=content||'';
    bubble.appendChild(span);
  }
  div.appendChild(bubble);
  var meta=document.createElement('div');
  meta.className='chat-meta';
  var now=new Date();
  var ts=now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0');
  meta.innerHTML=ts+(role==='agent'||role==='assistant' ? ' <span class="chat-model-tag">AI Agent</span>' : '');
  div.appendChild(meta);
  msgs.appendChild(div);
  msgs.scrollTop=msgs.scrollHeight;
  return div;
}

function appendSupportThinking(){
  var msgs=document.getElementById('supportMessages');
  var div=document.createElement('div');
  div.className='chat-thinking';
  div.innerHTML='<div class="chat-thinking-inner"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span class="chat-thinking-label">Думаю</span><div class="chat-dots"><div class="chat-dot"></div><div class="chat-dot"></div><div class="chat-dot"></div></div></div>';
  msgs.appendChild(div);
  msgs.scrollTop=msgs.scrollHeight;
  return div;
}

function sendSupportMessage(){
  if(_supportPending) return;
  var api=getApi(); if(!api) return;
  var ta=document.getElementById('supportInput');
  var text=(ta.value||'').trim();
  var hasImage=!!_supportImageBase64;
  if(!text && !hasImage) return;
  var imageData=_supportImageBase64;
  var attachBtn=document.getElementById('supportAttachBtn');
  ta.value=''; ta.style.height='';
  clearSupportAttachment();
  ta.disabled=true;
  if(attachBtn) attachBtn.classList.add('chat-attach-disabled');
  appendSupportMsg('user', text, imageData||null);
  var thinkEl=appendSupportThinking();
  _supportPending=true;
  document.getElementById('supportSendBtn').disabled=true;
  api('/api/support/chat','POST',{content:text||null, image_data:imageData||null}).then(function(d){
    thinkEl.remove();
    document.getElementById('supportCloseBtn').style.display='';
    if(d.error){
      appendSupportMsg('agent','Извините, произошла ошибка. Попробуйте ещё раз.',null);
    } else if(d.agent_message){
      appendSupportMsg('agent', d.agent_message.content, null);
    }
  }).catch(function(){
    thinkEl.remove();
    appendSupportMsg('agent','Ошибка сети. Проверьте соединение и попробуйте ещё раз.',null);
  }).finally(function(){
    _supportPending=false;
    ta.disabled=false;
    if(attachBtn) attachBtn.classList.remove('chat-attach-disabled');
    document.getElementById('supportSendBtn').disabled=false;
    ta.focus();
  });
}

function closeSupportChat(){
  var cc=window.customConfirm;
  if(!cc){ _doCloseSupportChat(); return; }
  cc('Завершение диалога','AI проанализирует переписку и при необходимости сообщит администратору. Завершить?').then(function(ok){
    if(!ok) return;
    _doCloseSupportChat();
  });
}

function _doCloseSupportChat(){
  var api=getApi(); if(!api) return;
  var btn=document.getElementById('supportCloseBtn');
  btn.disabled=true; btn.textContent='Завершение...';
  api('/api/support/close','POST',{}).then(function(d){
    document.getElementById('supportInput').disabled=true;
    document.getElementById('supportSendBtn').disabled=true;
    document.getElementById('supportCloseBtn').style.display='none';
    var newChatBtn=document.getElementById('supportNewChatBtn');
    if(newChatBtn) newChatBtn.style.display='';
    var status=document.getElementById('supportChatStatus');
    if(status) status.textContent='Диалог завершён';
    if(d.reported){
      toast('Обращение передано администратору','ok');
      appendSupportMsg('agent','Ваш диалог завершён. Я передал информацию о вашей проблеме администратору — он свяжется с вами через уведомления.',null);
    } else {
      toast('Диалог завершён','ok');
      appendSupportMsg('agent','Рад был помочь! Если возникнут новые вопросы — вернитесь в раздел поддержки.',null);
    }
  }).catch(function(){
    btn.disabled=false;
    btn.innerHTML='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Завершить диалог';
    toast('Ошибка при завершении диалога','err');
  });
}

function startNewSupportDialog(){
  var msgs=document.getElementById('supportMessages');
  var empty=document.getElementById('supportEmptyState');
  Array.from(msgs.querySelectorAll('.chat-msg,.chat-thinking')).forEach(function(el){el.remove();});
  if(empty) empty.style.display='flex';
  document.getElementById('supportInput').disabled=false;
  document.getElementById('supportSendBtn').disabled=false;
  document.getElementById('supportCloseBtn').style.display='none';
  var newChatBtn=document.getElementById('supportNewChatBtn');
  if(newChatBtn) newChatBtn.style.display='none';
  var status=document.getElementById('supportChatStatus');
  if(status) status.textContent='';
  _supportPending=false;
  clearSupportAttachment();
  document.getElementById('supportInput').focus();
}

function onSupportFileSelected(input){
  var file=input.files[0];
  if(!file) return;
  if(!file.type.startsWith('image/')){ toast('Выберите изображение','err'); input.value=''; return; }
  if(file.size > 10*1024*1024){ toast('Файл слишком большой (макс. 10 МБ)','err'); input.value=''; return; }
  var reader=new FileReader();
  reader.onload=function(e){
    _supportImageBase64=e.target.result;
    _supportImageName=file.name;
    document.getElementById('supportPreviewImg').src=_supportImageBase64;
    document.getElementById('supportPreviewName').textContent=file.name;
    document.getElementById('supportPreviewWrap').style.display='';
    document.getElementById('supportAttachBtn').classList.add('has-file');
  };
  reader.readAsDataURL(file);
  input.value='';
}

function clearSupportAttachment(){
  _supportImageBase64=''; _supportImageName='';
  var pw=document.getElementById('supportPreviewWrap'); if(pw) pw.style.display='none';
  var pi=document.getElementById('supportPreviewImg'); if(pi) pi.src='';
  var ab=document.getElementById('supportAttachBtn'); if(ab) ab.classList.remove('has-file');
}

/* ── Экспорт в window.* для inline onclick + view-роутера ── */
window.initSupportView       = initSupportView;
window.loadSupportHistory    = loadSupportHistory;
window.appendSupportMsg      = appendSupportMsg;
window.appendSupportThinking = appendSupportThinking;
window.sendSupportMessage    = sendSupportMessage;
window.closeSupportChat      = closeSupportChat;
window.startNewSupportDialog = startNewSupportDialog;
window.onSupportFileSelected = onSupportFileSelected;
window.clearSupportAttachment= clearSupportAttachment;

export {
  initSupportView,
  loadSupportHistory,
  appendSupportMsg,
  appendSupportThinking,
  sendSupportMessage,
  closeSupportChat,
  startNewSupportDialog,
  onSupportFileSelected,
  clearSupportAttachment,
};
