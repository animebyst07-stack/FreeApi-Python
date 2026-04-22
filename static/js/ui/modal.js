/* ui/modal.js — модальные окна и customConfirm.
   Шаг 0.5.8: вынесены из inline-скрипта static/index.html:
     window.openModal, window.closeModal, window.overlayClick, window.switchModal,
     window.customConfirm, window.resolveConfirm.

   Все функции выставлены в window.* для inline onclick="" в HTML и для
   classic-script callsites (handlers внутри inline-блока). */

export function openModal(id){
  var el = document.getElementById(id);
  if (!el) return;
  el.classList.add('open');
  document.body.style.overflow = 'hidden';
}

export function closeModal(id){
  var el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('open');
  document.body.style.overflow = '';
}

export function overlayClick(e, el){
  if (e && el && e.target === el) closeModal(el.id);
}

export function switchModal(from, to){
  closeModal(from);
  setTimeout(function(){ openModal(to); }, 100);
}

/* ───── customConfirm — Promise-based подтверждение через #confirmModal ───── */
var _confirmResolve = null;

export function customConfirm(title, message){
  return new Promise(function(resolve){
    _confirmResolve = resolve;
    var t = document.getElementById('confirmTitle');
    var m = document.getElementById('confirmMessage');
    if (t) t.textContent = title || 'Подтверждение';
    if (m) m.textContent = message || 'Вы уверены?';
    openModal('confirmModal');
  });
}

export function resolveConfirm(val){
  closeModal('confirmModal');
  if (_confirmResolve) {
    var r = _confirmResolve;
    _confirmResolve = null;
    r(val);
  }
}

window.openModal = openModal;
window.closeModal = closeModal;
window.overlayClick = overlayClick;
window.switchModal = switchModal;
window.customConfirm = customConfirm;
window.resolveConfirm = resolveConfirm;
