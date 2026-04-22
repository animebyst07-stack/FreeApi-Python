/* core/logger.js — клиентский логгер (шаг 0.5.4).
   Дублирует console.log/warn/error и шлёт строку в Termux через POST /api/_clog.
   Все callsites обёрнуты в try/catch, поэтому если модуль ещё не загружен
   (defer) — вызовы молча игнорируются.

   ВАЖНО: ранний логгер (window._clogRaw + JS_ERROR/JS_REJECT/CLICK
   перехватчики) остаётся inline в index.html, т.к. обязан подняться ДО
   парсинга основного скрипта. Этот модуль — только пользовательский clog. */

export function clog(tag, msg, level) {
  try {
    var line = '[' + tag + '] ' + msg;
    if (level === 'error') { console.error(line); }
    else if (level === 'warn') { console.warn(line); }
    else { console.log(line); }
  } catch (_) {}
  try {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/_clog', true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.timeout = 4000;
    xhr.send(JSON.stringify({
      tag: String(tag || 'CLIENT'),
      msg: String(msg == null ? '' : msg),
      level: level || 'info'
    }));
  } catch (_) {}
}

/* Глобальная регистрация — onclick="" в HTML и inline-callsites вида
   `clog(...)` (без префикса window.) обращаются к глобалу. */
window.clog = clog;
