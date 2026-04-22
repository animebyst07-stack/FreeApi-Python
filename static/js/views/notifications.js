/* views/notifications.js — уведомления (колокольчик + страница).
   Шаг 0.5.12: вынесено из inline-скрипта static/index.html.

   Зависимости: window.user (глобальное состояние, инлайн), window.api,
   window.clog, window.showToast (выставлены ESM-модулями ядра до загрузки
   этого модуля; используем window.* для устойчивости к порядку import). */

import { esc, formatDate } from '../core/dom.js';

/* Глобальные слоты на window — см. оригинал. */
window._notifPollTimer = null;
window._notifLastUnread = -1;

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
  _clog('NOTIF', 'GET /api/notifications');
  _api()('/api/notifications').then(function(d){
    var items = (d && d.notifications) || [];
    var unread = parseInt(d && d.unread || 0) || 0;
    _clog('NOTIF', 'OK total=' + items.length + ' unread=' + unread);
    if (unreadEl) {
      if (unread > 0) { unreadEl.textContent = unread + ' непрочит.'; unreadEl.style.display = 'inline-block'; }
      else unreadEl.style.display = 'none';
    }
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="notif-empty"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>Пока нет уведомлений</div>';
      return;
    }
    list.innerHTML = items.map(function(n){
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

export function markAllNotifsRead(silent){
  if (!window.user) return;
  _clog('NOTIF', 'POST /api/notifications/read_all silent=' + (!!silent));
  _api()('/api/notifications/read_all', 'POST', {}).then(function(d){
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
