/* views/notifications.js — уведомления (колокольчик + страница).
   Шаг 0.5.12: вынесено из inline-скрипта static/index.html.

   Зависимости: window.user (глобальное состояние, инлайн), window.api,
   window.clog, window.showToast (выставлены ESM-модулями ядра до загрузки
   этого модуля; используем window.* для устойчивости к порядку import). */

import { esc, formatDate } from '../core/dom.js';

/* Глобальные слоты на window — см. оригинал. */
window._notifPollTimer = null;
window._notifLastUnread = -1;
/* B2: текущий фильтр и последняя разбивка непрочитанных по типам. */
window._notifKindFilter = 'all';
window._notifUnreadByKind = { all: 0, review: 0, support: 0, system: 0 };

function _api(){ return window.api; }
function _clog(tag, msg, lvl){ try { if (window.clog) window.clog(tag, msg, lvl); } catch(_) {} }
function _toast(t, k){ if (window.showToast) window.showToast(t, k); }

export function refreshNotifBadge(){
  var bell = document.getElementById('topbarBell');
  var badge = document.getElementById('topbarBellBadge');
  if (!window.user) {
    if (bell) { bell.style.display = 'none'; bell.classList.remove('has-unread'); }
    if (badge) { badge.style.display = 'none'; badge.textContent = '0'; }
    return;
  }
  if (bell) bell.style.display = 'inline-flex';
  _api()('/api/notifications').then(function(d){
    var unread = parseInt(d && d.unread || 0) || 0;
    if (unread !== window._notifLastUnread) {
      _clog('NOTIF', 'badge update unread=' + unread);
      window._notifLastUnread = unread;
    }
    if (badge) {
      if (unread > 0) { badge.textContent = unread > 99 ? '99+' : unread; badge.style.display = 'inline-block'; }
      else { badge.style.display = 'none'; }
    }
    if (bell) bell.classList.toggle('has-unread', unread > 0);
  }).catch(function(){});
}

export function loadNotifications(){
  var list = document.getElementById('notifPageList');
  var unreadEl = document.getElementById('notifPageUnread');
  if (!window.user) {
    if (list) list.innerHTML = '<div class="notif-empty"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/></svg>Войдите, чтобы видеть уведомления</div>';
    if (unreadEl) unreadEl.style.display = 'none';
    return;
  }
  if (list) list.innerHTML = '<div class="notif-empty"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>Загрузка...</div>';
  /* B2: фильтр по типу (review|support|system|all). */
  var kind = window._notifKindFilter || 'all';
  var qs = (kind && kind !== 'all') ? ('?kind=' + encodeURIComponent(kind)) : '';
  _clog('NOTIF', 'GET /api/notifications' + qs);

  /* 0.5.13c: для админа параллельно тянем admin_notifications, чтобы
     показать единый список (раньше эти карточки висели отдельной плиткой
     в админ-панели — теперь, по требованию пользователя, всё в одном месте).
     B2: админ-уведомления показываем только во вкладках 'all' и 'support'
     (это запросы поддержки от пользователей). */
  var userP  = _api()('/api/notifications' + qs);
  var isAdm  = !!(window.user && window.user.username === 'ReZero');
  var showAdmin = isAdm && (kind === 'all' || kind === 'support');
  var adminP = showAdmin ? _api()('/api/admin/notifications').catch(function(){ return {notifications:[]}; })
                         : Promise.resolve({notifications:[]});

  Promise.all([userP, adminP]).then(function(arr){
    var d = arr[0] || {};
    var ad = arr[1] || {};
    var items = d.notifications || [];
    var adminItems = ad.notifications || [];
    var unread = parseInt(d.unread || 0) || 0;
    /* B2: разбивка по типам — обновляем счётчики на табах. */
    var byKind = d.unread_by_kind || { all: unread, review: 0, support: 0, system: 0 };
    window._notifUnreadByKind = byKind;
    _renderNotifTabsCounts(byKind);
    _renderActiveTab();
    _clog('NOTIF', 'OK total=' + items.length + ' admin=' + adminItems.length + ' unread=' + unread + ' kind=' + (window._notifKindFilter || 'all'));
    if (unreadEl) {
      if (unread > 0) { unreadEl.textContent = unread + ' непрочит.'; unreadEl.style.display = 'inline-block'; }
      else unreadEl.style.display = 'none';
    }
    if (!list) return;
    if (!items.length && !adminItems.length) {
      list.innerHTML = '<div class="notif-empty"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>Пока нет уведомлений</div>';
      return;
    }

    var html = items.map(function(n){
      var unr = !n.is_read;
      return '<div class="notif-card' + (unr ? ' unread' : '') + '" data-notif-id="' + esc(n.id) + '">'
        + '<div class="notif-card-msg">' + esc(n.message || '') + '</div>'
        + '<div class="notif-card-foot">'
          + '<span>' + (unr ? '<span class="ndot"></span>Новое · ' : '') + formatDate(n.created_at) + '</span>'
          + '<button class="btn btn-ghost btn-xs" type="button" onclick="deleteUserNotification(\'' + esc(n.id) + '\')" aria-label="Удалить уведомление">'
            + '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>'
            + 'Удалить'
          + '</button>'
        + '</div>'
      + '</div>';
    }).join('');

    /* Админ-карточки. Свёрнутый блок: только review_text (краткое summary
       от ИИ-агента поддержки). Кнопка «Подробнее» раскрывает ai_advice
       (детали отчёта). Если support_chat_id задан — дополнительная кнопка
       «Открыть диалог» вызывает модалку с полной перепиской. */
    if (adminItems.length) {
      html += adminItems.map(function(n){
        var details = (n.ai_advice || '').trim();
        var hasChat = !!n.support_chat_id;
        return '<div class="notif-card admin-notif" data-admin-notif-id="' + esc(n.id) + '">'
          + '<div class="notif-card-msg"><b>' + esc(n.review_text || '(без темы)') + '</b></div>'
          + (details ? '<div class="notif-admin-details" style="display:none;margin-top:8px;padding:10px 12px;background:#0a0a0a;border:1px solid #141414;border-radius:8px;color:#bdc1c6;font-size:13px;white-space:pre-wrap">' + esc(details) + '</div>' : '')
          + '<div class="notif-card-foot" style="flex-wrap:wrap;gap:6px">'
            + '<span>' + formatDate(n.created_at) + '</span>'
            + '<span style="display:flex;gap:6px;flex-wrap:wrap">'
              + (details ? '<button class="btn btn-ghost btn-xs" type="button" onclick="toggleAdminNotifDetails(\'' + esc(n.id) + '\', this)">Подробнее</button>' : '')
              + (hasChat ? '<button class="btn btn-ghost btn-xs" type="button" onclick="openSupportChatModal(\'' + esc(n.support_chat_id) + '\')">Открыть диалог</button>' : '')
              + '<button class="btn btn-ghost btn-xs" type="button" onclick="deleteAdminNotifFromPage(\'' + esc(n.id) + '\')">Удалить</button>'
            + '</span>'
          + '</div>'
        + '</div>';
      }).join('');
    }

    list.innerHTML = html;

    /* Авто-пометка прочитанным через 1.2с */
    if (unread > 0) {
      setTimeout(function(){
        var v = document.getElementById('view-notifications');
        if (v && v.classList.contains('active')) {
          markAllNotifsRead(true);
        }
      }, 1200);
    }
  }).catch(function(e){
    _clog('NOTIF', 'ERR ' + e, 'error');
    if (list) list.innerHTML = '<div class="notif-empty">Не удалось загрузить уведомления</div>';
  });
}

/* Раскрытие/сворачивание подробностей админ-уведомления. */
export function toggleAdminNotifDetails(id, btn){
  var card = document.querySelector('[data-admin-notif-id="' + id + '"]');
  if (!card) return;
  var det = card.querySelector('.notif-admin-details');
  if (!det) return;
  var open = det.style.display !== 'none';
  det.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? 'Подробнее' : 'Свернуть';
}

/* Удаление админ-уведомления прямо со страницы /notifications. */
export function deleteAdminNotifFromPage(id){
  _api()('/api/admin/notifications/' + id, 'DELETE').then(function(){
    var card = document.querySelector('[data-admin-notif-id="' + id + '"]');
    if (card && card.parentNode) card.parentNode.removeChild(card);
    var list = document.getElementById('notifPageList');
    if (list && !list.children.length) loadNotifications();
  }).catch(function(){ _toast('Ошибка', 'err'); });
}

/* Модалка «Открыть диалог поддержки» — полный список сообщений по chat_id.
   Используем уже существующий esc/formatDate из core/dom. Лёгкая собственная
   разметка — без зависимостей от внешних модалок (в проекте есть только
   customConfirm для да/нет). Закрывается по клику на фон или по Esc. */
export function openSupportChatModal(chatId){
  var api = _api();
  if (!api) return;
  /* Удалить старую модалку если осталась. */
  var prev = document.getElementById('supportChatModal');
  if (prev && prev.parentNode) prev.parentNode.removeChild(prev);

  var ov = document.createElement('div');
  ov.id = 'supportChatModal';
  ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px';
  ov.innerHTML =
    '<div style="background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px;width:100%;max-width:680px;max-height:88vh;display:flex;flex-direction:column;overflow:hidden">'
      + '<div style="padding:14px 16px;border-bottom:1px solid #141414;display:flex;justify-content:space-between;align-items:center;gap:12px">'
        + '<div style="font-weight:600;color:#e8eaed">Диалог поддержки</div>'
        + '<button class="btn btn-ghost btn-xs" type="button" id="supportChatModalClose">Закрыть</button>'
      + '</div>'
      + '<div id="supportChatModalBody" style="padding:16px;overflow-y:auto;flex:1;color:#bdc1c6;font-size:13px;line-height:1.5">Загрузка…</div>'
    + '</div>';
  document.body.appendChild(ov);

  function close(){
    if (ov.parentNode) ov.parentNode.removeChild(ov);
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e){ if (e.key === 'Escape') close(); }
  ov.addEventListener('click', function(e){ if (e.target === ov) close(); });
  document.getElementById('supportChatModalClose').addEventListener('click', close);
  document.addEventListener('keydown', onKey);

  api('/api/admin/support/chat/' + chatId).then(function(d){
    var body = document.getElementById('supportChatModalBody');
    if (!body) return;
    if (!d || d.error) { body.innerHTML = '<div style="color:#888">Не удалось загрузить диалог.</div>'; return; }
    var head = '<div style="margin-bottom:10px;font-size:12px;color:#888">Пользователь: <b style="color:#e8eaed">@' + esc(d.chat.username) + '</b> · статус: ' + esc(d.chat.status) + '</div>';
    var msgs = (d.messages || []).filter(function(m){ return m.role !== 'agent_step'; }).map(function(m){
      var who = m.role === 'user' ? 'Пользователь' : (m.role === 'agent' ? 'AI Agent' : m.role);
      var color = m.role === 'user' ? '#9aa0a6' : '#7eb6ff';
      var img = m.image_data ? '<div style="margin-top:6px"><img src="' + esc(m.image_data) + '" style="max-width:200px;max-height:160px;border-radius:6px;border:1px solid #1e1e1e"></div>' : '';
      return '<div style="margin-bottom:14px"><div style="font-size:11px;color:' + color + ';margin-bottom:4px">' + esc(who) + ' · ' + formatDate(m.created_at) + '</div>'
        + '<div style="white-space:pre-wrap;color:#e8eaed">' + esc(m.content || '') + '</div>' + img + '</div>';
    }).join('');
    body.innerHTML = head + (msgs || '<div style="color:#888">Сообщений нет.</div>');
  }).catch(function(){
    var body = document.getElementById('supportChatModalBody');
    if (body) body.innerHTML = '<div style="color:#888">Сеть не отвечает.</div>';
  });
}

/* B2: переключение вкладки фильтра. */
export function setNotifKind(kind){
  var k = (kind || 'all').toString();
  if (['all','review','support','system'].indexOf(k) < 0) k = 'all';
  if (window._notifKindFilter === k) return;
  window._notifKindFilter = k;
  _renderActiveTab();
  loadNotifications();
}

function _renderActiveTab(){
  var tabs = document.querySelectorAll('#notifTabs .notif-tab');
  if (!tabs || !tabs.length) return;
  var cur = window._notifKindFilter || 'all';
  for (var i = 0; i < tabs.length; i++) {
    var t = tabs[i];
    if (t.getAttribute('data-notif-kind') === cur) t.classList.add('active');
    else t.classList.remove('active');
  }
}

function _renderNotifTabsCounts(byKind){
  var box = document.getElementById('notifTabs');
  if (!box) return;
  var keys = ['all','review','support','system'];
  for (var i = 0; i < keys.length; i++){
    var k = keys[i];
    var el = box.querySelector('[data-cnt-for="' + k + '"]');
    if (!el) continue;
    var n = parseInt((byKind && byKind[k]) || 0) || 0;
    if (n > 0) { el.textContent = n; el.hidden = false; }
    else { el.textContent = '0'; el.hidden = true; }
  }
}

export function markAllNotifsRead(silent){
  if (!window.user) return;
  /* B2: если активен фильтр-вкладка — помечаем прочитанным только её. */
  var kind = window._notifKindFilter || 'all';
  var url = '/api/notifications/read_all' + (kind !== 'all' ? ('?kind=' + encodeURIComponent(kind)) : '');
  _clog('NOTIF', 'POST ' + url + ' silent=' + (!!silent));
  _api()(url, 'POST', {}).then(function(d){
    _clog('NOTIF', 'read_all OK updated=' + ((d && d.updated) || 0));
    if (!silent) _toast('Все уведомления отмечены прочитанными', 'ok');
    document.querySelectorAll('#notifPageList .notif-card.unread').forEach(function(c){ c.classList.remove('unread'); });
    var unreadEl = document.getElementById('notifPageUnread');
    if (unreadEl) unreadEl.style.display = 'none';
    refreshNotifBadge();
  }).catch(function(){
    if (!silent) _toast('Ошибка', 'err');
  });
}

export function deleteUserNotification(id){
  _clog('NOTIF', 'DELETE id=' + id);
  _api()('/api/notifications/' + id, 'DELETE').then(function(){
    var card = document.querySelector('[data-notif-id="' + id + '"]');
    if (card) {
      card.style.transition = 'opacity .2s,transform .2s';
      card.style.opacity = '0';
      card.style.transform = 'translateX(20px)';
      setTimeout(function(){
        if (card.parentNode) card.parentNode.removeChild(card);
        var list = document.getElementById('notifPageList');
        if (list && !list.children.length) loadNotifications();
      }, 220);
    }
    refreshNotifBadge();
  }).catch(function(){ _toast('Ошибка', 'err'); });
}

export function startNotifPolling(){
  if (window._notifPollTimer) return;
  refreshNotifBadge();
  window._notifPollTimer = setInterval(refreshNotifBadge, 60000);
  _clog('NOTIF', 'polling started (60s)');
}

export function stopNotifPolling(){
  if (window._notifPollTimer) {
    clearInterval(window._notifPollTimer);
    window._notifPollTimer = null;
    _clog('NOTIF', 'polling stopped');
  }
}

/* Совместимость со старым inline-кодом: пустой shim. */
export function loadUserNotifications(){ refreshNotifBadge(); }

window.refreshNotifBadge      = refreshNotifBadge;
window.loadNotifications      = loadNotifications;
window.markAllNotifsRead      = markAllNotifsRead;
window.deleteUserNotification = deleteUserNotification;
window.startNotifPolling      = startNotifPolling;
window.stopNotifPolling       = stopNotifPolling;
window.loadUserNotifications  = loadUserNotifications;
/* 0.5.13c: новые функции для админ-карточек на странице /notifications. */
window.toggleAdminNotifDetails = toggleAdminNotifDetails;
window.deleteAdminNotifFromPage = deleteAdminNotifFromPage;
window.openSupportChatModal    = openSupportChatModal;
window.setNotifKind            = setNotifKind;
