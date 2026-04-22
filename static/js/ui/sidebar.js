/* ui/sidebar.js — мобильный сайдбар (открыть/закрыть/тоггл).
   Шаг 0.5.9: вынесены `window.toggleSidebar`, `window.closeSidebar` из inline.
   `updateSidebar()` — пока остаётся inline (зависит от user/accountState/admin-флагов;
   будет вынесена позже вместе с состоянием).

   Дополнительно регистрируется обработчик resize: при возврате на десктоп
   (>=900px) — авто-закрытие. Раньше это был отдельный inline-listener. */

export function toggleSidebar(){
  var sb = document.getElementById('sidebar');
  var ov = document.getElementById('sidebarOverlay');
  var hb = document.getElementById('hamburger');
  if (!sb) return;
  var open = sb.classList.toggle('open');
  if (ov) ov.classList.toggle('open', open);
  if (hb) hb.classList.toggle('open', open);
  document.body.classList.toggle('sidebar-locked', open);
}

export function closeSidebar(){
  var sb = document.getElementById('sidebar');
  var ov = document.getElementById('sidebarOverlay');
  var hb = document.getElementById('hamburger');
  if (sb) sb.classList.remove('open');
  if (ov) ov.classList.remove('open');
  if (hb) hb.classList.remove('open');
  document.body.classList.remove('sidebar-locked');
}

window.toggleSidebar = toggleSidebar;
window.closeSidebar = closeSidebar;

/* Resize → закрываем сайдбар на десктопе. Регистрируем единожды;
   модуль импортируется только из main.js, так что повторов не будет. */
window.addEventListener('resize', function(){
  if (window.innerWidth >= 900) closeSidebar();
});
