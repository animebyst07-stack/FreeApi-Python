/* core/api.js — XHR-обёртка над fetch'ем для Termux/Android WebView.
   Шаг 0.5.5: вынесена из inline-скрипта static/index.html (бывшая `function api(...)`).

   Возвращает Promise. Используется через window.api (для inline-кода и handlers).
   Логирует через ранний window._clogRaw, чтобы не зависеть от полного логгера.

   Зависимости из глобалки (top-level var в classic-script = window.X после
   снятия IIFE на шаге 0.5.3a):
     window.user, window.accountState  — состояние авторизации
     window.updateSidebar, window.goView, window.showToast — UI-помощники
   Все обращения через window.* — модуль ESM не имеет прямого доступа к ним. */

/* opts.timeout — кастомный таймаут в мс (по умолчанию 15000). Нужен для
   длительных операций вроде /api/support/close, где Сэм через Telethon
   спокойно отвечает 30+ секунд, и стандартные 15с дают ложный TIMEOUT. */
export function api(url, method, body, opts){
  var _t0 = Date.now();
  var _m  = (method || 'GET').toUpperCase();
  var _bs = body ? (typeof body === 'string' ? body.length : JSON.stringify(body).length) : 0;
  var _to = (opts && typeof opts.timeout === 'number') ? opts.timeout : 15000;
  try { window._clogRaw && url.indexOf('/api/_clog') < 0 && window._clogRaw('API_CALL','→ ' + _m + ' ' + url + ' body=' + _bs + 'b'); } catch(_) {}

  return new Promise(function(resolve, reject){
    var xhr = new XMLHttpRequest();
    xhr.open(method || 'GET', url, true);
    xhr.withCredentials = true;
    xhr.timeout = _to;
    if (body) xhr.setRequestHeader('Content-Type', 'application/json');

    xhr.ontimeout = function(){
      try { window._clogRaw && url.indexOf('/api/_clog') < 0 && window._clogRaw('API_CALL','✗ ' + _m + ' ' + url + ' TIMEOUT ' + (Date.now() - _t0) + 'ms','error'); } catch(_) {}
      reject(new Error('timeout'));
    };
    xhr.onerror = function(){
      try { window._clogRaw && url.indexOf('/api/_clog') < 0 && window._clogRaw('API_CALL','✗ ' + _m + ' ' + url + ' NETWORK ' + (Date.now() - _t0) + 'ms','error'); } catch(_) {}
      reject(new Error('network'));
    };
    xhr.onload = function(){
      var data = {};
      try { if (xhr.responseText) data = JSON.parse(xhr.responseText); } catch(e) {}
      try { window._clogRaw && url.indexOf('/api/_clog') < 0 && window._clogRaw('API_CALL','← ' + _m + ' ' + url + ' status=' + xhr.status + ' resp=' + (xhr.responseText ? xhr.responseText.length : 0) + 'b ' + (Date.now() - _t0) + 'ms'); } catch(_) {}

      if (xhr.status === 401 && window.user) {
        window.user = null;
        window.accountState = null;
        if (typeof window.updateSidebar === 'function') window.updateSidebar();
        var onProtected = ['dashboard','cabinet','chat','admin'].some(function(v){
          var el = document.getElementById('view-' + v);
          return el && el.classList.contains('active');
        });
        if (onProtected && typeof window.goView === 'function') window.goView('landing');
        if (typeof window.showToast === 'function') window.showToast('Сессия истекла. Войдите снова.','err');
      }
      if (xhr.status < 200 || xhr.status >= 300) { if (typeof data === 'object') data.status = xhr.status; }
      resolve(data);
    };

    xhr.send(body ? JSON.stringify(body) : null);
  });
}

window.api = api;
