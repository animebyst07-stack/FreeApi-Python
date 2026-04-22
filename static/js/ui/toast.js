/* ui/toast.js — всплывающие уведомления (F-04).
   Шаг 0.5.7: вынесена `window.showToast` из inline-скрипта static/index.html.

   Зависимости из глобалки (top-level var classic-script = window.X):
     window.q   — алиас getElementById (см. core/dom.js / inline-bootstrap)
     window.esc — экранирование HTML (см. core/dom.js / inline-bootstrap)

   Контейнер #toastWrap должен присутствовать в DOM (статический div в index.html).
   Лимит — максимум 4 одновременных тоста (старые удаляются). */

export function showToast(msg, type){
  var q = window.q || function(id){ return document.getElementById(id); };
  var esc = window.esc || function(s){
    var d = document.createElement('div');
    d.textContent = String(s == null ? '' : s);
    return d.innerHTML;
  };
  var wrap = q('toastWrap');
  if (!wrap) return;

  var t = document.createElement('div');
  t.className = 'toast' + (type === 'ok' ? ' toast-ok' : type === 'err' ? ' toast-err' : '');

  var icon = type === 'ok'
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>'
    : type === 'err'
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  t.innerHTML = icon + esc(msg);

  while (wrap.children.length >= 4) {
    var oldest = wrap.firstChild;
    if (oldest) { oldest.classList.remove('show'); wrap.removeChild(oldest); }
  }
  wrap.appendChild(t);

  requestAnimationFrame(function(){
    requestAnimationFrame(function(){ t.classList.add('show'); });
  });
  setTimeout(function(){
    t.classList.remove('show');
    setTimeout(function(){ if (t.parentNode) t.parentNode.removeChild(t); }, 300);
  }, 3500);
}

window.showToast = showToast;
