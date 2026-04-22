/* core/dom.js — чистые DOM-утилиты, без зависимостей от состояния SPA.
   Перенесено из static/index.html (шаг 0.5.2). */

export function q(id){
  return document.getElementById(id);
}

export function esc(s){
  var d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

export function formatDate(v){
  if(!v) return '—';
  var d = new Date(String(v).replace(' ', 'T'));
  if(isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('ru-RU', {day:'2-digit', month:'2-digit', year:'numeric'})
       + ' '
       + d.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
}
