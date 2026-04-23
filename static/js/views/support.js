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
      if(m.role==='agent_step'){
        // Для шага агента в image_data лежит не картинка, а имена запрошенных
        // тегов документации (через запятую). Передаём их 4-м аргументом.
        appendSupportMsg('agent_step', m.content, null, m.image_data);
      } else {
        appendSupportMsg(m.role, m.content, m.image_data);
      }
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

function appendSupportMsg(role, content, imageSrc, docTag){
  var msgs=document.getElementById('supportMessages');
  var empty=document.getElementById('supportEmptyState');
  if(empty) empty.style.display='none';

  // Промежуточный шаг агента: компактный пузырь с SVG-иконкой книги
  // и пометкой «Читаю документацию: NAME». Эмодзи на сайте принципиально
  // не используем — только инлайн-SVG в общей стилистике интерфейса.
  // Текст шага (то, что ИИ написал перед тегом, например «Сейчас уточню,
  // как работают отзывы…») показываем под пометкой курсивом.
  if(role==='agent_step'){
    var sdiv=document.createElement('div');
    sdiv.className='chat-msg assistant';
    var sbub=document.createElement('div');
    sbub.className='chat-bubble';
    sbub.style.cssText='background:#1a1a1a;border:1px dashed #2a2a2a;color:#9aa0a6;font-size:12px;padding:8px 12px';
    var head=document.createElement('div');
    head.style.cssText='display:flex;align-items:center;gap:6px;color:#bdc1c6';
    head.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex:0 0 auto"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg><span>Читаю документацию: <b style="color:#e8eaed">'+(docTag||'…')+'</b></span>';
    sbub.appendChild(head);
    var stext=(content||'').trim();
    if(stext && stext!=='(читаю документацию...)'){
      var t=document.createElement('div');
      t.style.cssText='margin-top:4px;font-style:italic;color:#9aa0a6';
      t.textContent=stext;
      sbub.appendChild(t);
    }
    sdiv.appendChild(sbub);
    msgs.appendChild(sdiv);
    msgs.scrollTop=msgs.scrollHeight;
    return sdiv;
  }

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
  api('/api/support/chat','POST',{content:text||null, image_data:imageData||null},{timeout:0}).then(function(d){
    thinkEl.remove();
    document.getElementById('supportCloseBtn').style.display='';
    if(d.error){
      appendSupportMsg('agent','Извините, произошла ошибка. Попробуйте ещё раз.',null);
    } else {
      // Сначала отрисовываем все промежуточные шаги (если ИИ читал документацию),
      // в порядке выполнения. Затем — финальный ответ агента.
      if(d.steps && d.steps.length){
        d.steps.forEach(function(s){
          appendSupportMsg('agent_step', s.content, null, s.image_data);
        });
      }
      if(d.agent_message){
        appendSupportMsg('agent', d.agent_message.content, null);
      }
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

/* Анти-double-click: пока первый /api/support/close ещё крутится у Сэма
   через Telethon (это спокойно 30+ секунд), второй клик ловил KEY_BUSY_301
   и триггерил сломанный fallback по словам. Теперь, пока запрос «висит»,
   повторный клик просто игнорируется. */
window._supportClosing = window._supportClosing || false;

function _doCloseSupportChat(){
  if (window._supportClosing) return;          /* уже идёт — выходим тихо */
  var api=getApi(); if(!api) return;
  var btn=document.getElementById('supportCloseBtn');
  window._supportClosing = true;
  btn.disabled=true; btn.textContent='Завершение...';
  /* Таймаут 90с — чтобы фронт не сдавался раньше Сэма; toast'ов больше
     не показываем (по требованию: все статусы — только в чате и на
     странице уведомлений). */
  api('/api/support/close','POST',{},{timeout:90000}).then(function(d){
    document.getElementById('supportInput').disabled=true;
    document.getElementById('supportSendBtn').disabled=true;
    document.getElementById('supportCloseBtn').style.display='none';
    var newChatBtn=document.getElementById('supportNewChatBtn');
    if(newChatBtn) newChatBtn.style.display='';
    var status=document.getElementById('supportChatStatus');
    if(status) status.textContent='Диалог завершён';
    if(d && d.reported){
      appendSupportMsg('agent','Диалог завершён. Я передал ваш вопрос администратору — ответ придёт в раздел «Уведомления».',null);
    } else {
      appendSupportMsg('agent','Рад был помочь! Если появятся новые вопросы — вернитесь в раздел поддержки.',null);
    }
  }).catch(function(){
    /* Таймаут / сеть упала. Кнопку возвращаем, чтобы можно было повторить;
       сообщение пишем прямо в чат (без всплывающих окон). */
    btn.disabled=false;
    btn.innerHTML='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Завершить диалог';
    appendSupportMsg('agent','Не удалось завершить диалог: сеть не отвечает. Подождите несколько секунд и попробуйте снова.',null);
  }).finally(function(){
    window._supportClosing = false;
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
