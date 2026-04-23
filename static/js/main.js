/* main.js — entry-point модульной фронтенд-сборки.
   ВНИМАНИЕ ПО ПОРЯДКУ ЗАГРУЗКИ:
   <script type="module"> исполняется в режиме defer, ПОСЛЕ парсинга DOM
   и ПОСЛЕ всех inline classic-<script>. Поэтому нельзя выставлять отсюда
   window.X для функций, нужных синхронно — inline IIFE упадёт с
   ReferenceError. Такие хелперы остаются продублированы в inline-скрипте
   до момента, когда сам IIFE будет перенесён в модуль. */

import './core/dom.js';     // q/esc/formatDate (для будущих ESM-консументов)
import './core/api.js';
import './core/logger.js';
import './core/storage.js';
import './core/state.js';

import './ui/toast.js';
import './ui/modal.js';
import './ui/sidebar.js';
import './ui/topbar.js';
import './ui/select.js';
import './ui/view.js';

import './views/auth.js';
import './views/keys.js';
import './views/setup.js';
import './views/chat.js';
import './views/reviews.js';
import './views/notifications.js';
import './views/support.js';
import './views/admin.js';
import './views/stats.js';
import './views/models.js';
import './views/docs.js';
import './views/logcodes.js';

window.__FPA_MAIN_LOADED__ = true;
console.debug('[FPA] main.js loaded (step 0.5.13-fix)');

/* Шаг 0.5.13-FIX: явный лог в Termux о готовности ESM —
   полезно для отладки порядка загрузки. */
try {
  if (window.clog) {
    window.clog('ESM','main.js loaded; modules ready: api='
      + (typeof window.api) + ' clog=' + (typeof window.clog)
      + ' showToast=' + (typeof window.showToast)
      + ' goView=' + (typeof window.goView)
      + ' lsGet=' + (typeof window.lsGet)
      + ' refreshNotifBadge=' + (typeof window.refreshNotifBadge));
  }
} catch (_) {}

/* Глобальный логгер unhandledrejection — отдельно от inline window.onerror. */
window.addEventListener('unhandledrejection', function(ev){
  try {
    var reason = ev && ev.reason;
    var msg = reason && reason.message ? reason.message : String(reason);
    var stack = reason && reason.stack ? String(reason.stack).slice(0, 1500) : '';
    if (window.clog) window.clog('JS_PROMISE_REJECT', msg + (stack ? ' || stack=' + stack : ''), 'error');
  } catch (_) {}
});
