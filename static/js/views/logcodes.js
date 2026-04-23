/* views/logcodes.js — модуль раздела «Коды логов» (шаг 0.5e).
   Перенесён из inline-блока static/index.html (~1635..1672).

   Это полноразмерный раздел #view-logcodes с расширенным набором
   категорий и иконок (Промокоды / Изображения / Подсказки и т.д.) —
   отличается от docs.js, который рендерит компактную версию внутри
   страницы документации.

   ВНЕШНИЕ ЗАВИСИМОСТИ (из inline-скрипта, через window.*):
     - window.api  — XHR-обёртка
     - window.q    — getElementById helper (inline)
     - window.esc  — html-escape helper (inline)
*/

(function(){
  function _api(){ return window.api; }
  function _q(id){ return window.q ? window.q(id) : document.getElementById(id); }
  function _esc(s){ return window.esc ? window.esc(s) : String(s == null ? '' : s); }

  var logCodesLoaded = false;

  function loadLogCodes(){
    if (logCodesLoaded) return;
    logCodesLoaded = true;
    _api()('/api/log-codes').then(function(d){
      var codes = d.codes || [];
      var groups = {};
      codes.forEach(function(c){
        if (!groups[c.category]) groups[c.category] = [];
        groups[c.category].push(c);
      });
      var catIcons = {
        'Запросы':    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
        'Ключи':      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
        'Telegram':   '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6z"/></svg>',
        'Настройка':  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>',
        'Спонсоры':   '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        'Модели':     '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/></svg>',
        'Промокоды':  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
        'Управление': '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
        'Изображения':'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
        'Подсказки':  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
      };
      var html = Object.keys(groups).map(function(cat){
        var icon = catIcons[cat] || '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>';
        var rows = groups[cat].map(function(c){
          return '<div class="log-row">' +
            '<div class="log-code-cell">' + _esc(c.code) + '</div>' +
            '<div class="log-info">' +
              '<div class="log-desc">' + _esc(c.description) + '</div>' +
              (c.solution ? '<div class="log-sol">' + icon + '<span>' + _esc(c.solution) + '</span></div>' : '') +
            '</div>' +
          '</div>';
        }).join('');
        return '<div class="log-cat"><div class="log-cat-title">' + icon + _esc(cat) + '</div><div class="log-table">' + rows + '</div></div>';
      }).join('');
      var cont = _q('logCodesContainer');
      if (cont) cont.innerHTML = html || '<div style="color:#555;font-size:13px">Нет данных</div>';
    }).catch(function(){
      var cont = _q('logCodesContainer');
      if (cont) cont.innerHTML = '<div style="color:#666;font-size:13px">Ошибка загрузки</div>';
    });
  }

  /* ── Экспорт в window.* ── */
  window.loadLogCodes = loadLogCodes;
})();
