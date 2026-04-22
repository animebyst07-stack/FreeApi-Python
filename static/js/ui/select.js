/* ui/select.js — кастомный dropdown (.custom-select-wrap).
   Шаг 0.5.10: вынесены `window.toggleCustomSelect` и `buildCustomSelect`
   из inline-скрипта static/index.html.

   buildCustomSelect использовался как top-level-функция (без `window.`),
   её callsites — внутри inline-функций (openKeySettings, loadAdminSettings,
   chat.* и др.). После выноса даём window.buildCustomSelect, чтобы
   classic-script-callsites продолжали работать.

   Поведение 1-в-1 с inline-оригиналом:
     - onChange(value, label) — два аргумента
     - selectedValue устанавливает только label.textContent (hidden НЕ трогаем)
     - глобальный click-handler закрывает все открытые dropdown'ы при клике вне */

export function toggleCustomSelect(triggerOrId){
  var wrap;
  if (typeof triggerOrId === 'string') {
    wrap = document.getElementById(triggerOrId);
  } else if (triggerOrId && triggerOrId.closest) {
    wrap = triggerOrId.closest('.custom-select-wrap');
  }
  if (!wrap) return;
  var wasOpen = wrap.classList.contains('open');
  document.querySelectorAll('.custom-select-wrap.open').forEach(function(w){
    w.classList.remove('open');
  });
  if (!wasOpen) wrap.classList.add('open');
}

export function buildCustomSelect(wrapId, options, selectedValue, onChange){
  var wrap = document.getElementById(wrapId);
  if (!wrap) return;
  var dropdown = wrap.querySelector('.custom-select-dropdown');
  var hidden = wrap.querySelector('input[type="hidden"]');
  var label = wrap.querySelector('.custom-select-label');
  if (!dropdown || !label) return;
  dropdown.innerHTML = '';
  var found = false;
  options.forEach(function(opt){
    var div = document.createElement('div');
    div.className = 'custom-select-option' + (opt.value === selectedValue ? ' selected' : '');
    div.textContent = opt.label;
    div.setAttribute('data-value', opt.value);
    div.onclick = function(){
      if (hidden) hidden.value = opt.value;
      label.textContent = opt.label;
      dropdown.querySelectorAll('.custom-select-option').forEach(function(o){
        o.classList.remove('selected');
      });
      div.classList.add('selected');
      wrap.classList.remove('open');
      if (onChange) onChange(opt.value, opt.label);
    };
    dropdown.appendChild(div);
    if (opt.value === selectedValue) { label.textContent = opt.label; found = true; }
  });
  if (!found && options.length > 0) {
    label.textContent = options[0].label;
    if (hidden) hidden.value = options[0].value;
  }
}

window.toggleCustomSelect = toggleCustomSelect;
window.buildCustomSelect = buildCustomSelect;

/* Закрытие открытых dropdown'ов по клику вне любого .custom-select-wrap */
document.addEventListener('click', function(e){
  if (!e.target.closest('.custom-select-wrap')) {
    document.querySelectorAll('.custom-select-wrap.open').forEach(function(w){
      w.classList.remove('open');
    });
  }
});
