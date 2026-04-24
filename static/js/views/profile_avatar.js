/* views/profile_avatar.js — G5: загрузка и кадрирование аватарки профиля.

   Полностью vanilla, без сторонних кропперов. Логика:
     1. Клик по .sb-avatar (только если data-auth="1") → скрытый <input type=file>.
     2. onchange → openAvatarCropper(file): off-screen Image → отображение в
        canvas 320×320 с маской квадрата, drag/wheel/pinch zoom.
     3. «Применить» → второй canvas 256×256 → toBlob(jpeg) с понижением
        качества до ≤180 KB → FileReader → base64 → PUT /api/auth/avatar.
     4. После сохранения — renderSidebarAvatar(user).

   Все строки на русском (правило проекта). Эмодзи запрещены.
*/

var MAX_BYTES = 200 * 1024;
var TARGET_BYTES = 180 * 1024;
var QUALITY_STEPS = [0.92, 0.85, 0.78];
var FINAL_SIZE = 256;
var PREVIEW_SIZE = 320;

/* ───── Состояние кропа (в одной модалке за раз) ───── */
var _img = null;        // HTMLImageElement исходника
var _scale = 1;         // текущий зум
var _minScale = 1;
var _maxScale = 8;
var _ox = 0, _oy = 0;   // смещение центра картинки относительно центра canvas
var _drag = null;       // {x, y, ox, oy}
var _pinchDist = null;
var _canvas = null;
var _ctx = null;
var _hasExisting = false; // показывать ли кнопку «Сбросить»

/* ───── Утилиты ───── */
function $(id){ return document.getElementById(id); }
function toast(msg, type){ if (window.showToast) window.showToast(msg, type); }

function fileToImage(file){
  return new Promise(function(resolve, reject){
    var fr = new FileReader();
    fr.onerror = function(){ reject(new Error('Не удалось прочитать файл')); };
    fr.onload = function(){
      var img = new Image();
      img.onload = function(){ resolve(img); };
      img.onerror = function(){ reject(new Error('Не удалось декодировать изображение')); };
      img.src = fr.result;
    };
    fr.readAsDataURL(file);
  });
}

/* Отрисовка превью + квадратной маски. Картинка центрируется по
   (PREVIEW_SIZE/2 + _ox, PREVIEW_SIZE/2 + _oy) и масштабируется на _scale
   относительно «обложки» (cover) PREVIEW_SIZE×PREVIEW_SIZE. */
function _drawPreview(){
  if (!_ctx || !_img) return;
  var W = PREVIEW_SIZE, H = PREVIEW_SIZE;
  _ctx.clearRect(0, 0, W, H);
  _ctx.fillStyle = '#000';
  _ctx.fillRect(0, 0, W, H);

  // base — масштаб «cover» (минимально, чтобы картинка покрыла квадрат)
  var base = Math.max(W / _img.naturalWidth, H / _img.naturalHeight);
  var s = base * _scale;
  var dw = _img.naturalWidth * s;
  var dh = _img.naturalHeight * s;
  var dx = (W - dw) / 2 + _ox;
  var dy = (H - dh) / 2 + _oy;
  _ctx.drawImage(_img, dx, dy, dw, dh);

  // Затемнение вне «активной» области (оставляем весь квадрат активным —
  // он же и есть финальный кадр). Рисуем только тонкую рамку.
  _ctx.strokeStyle = 'rgba(255,255,255,.55)';
  _ctx.lineWidth = 2;
  _ctx.strokeRect(1, 1, W - 2, H - 2);
}

/* Ограничиваем смещение, чтобы картинка не «уезжала» с квадрата. */
function _clampOffset(){
  if (!_img) return;
  var W = PREVIEW_SIZE;
  var base = Math.max(W / _img.naturalWidth, W / _img.naturalHeight);
  var s = base * _scale;
  var dw = _img.naturalWidth * s;
  var dh = _img.naturalHeight * s;
  var maxX = Math.max(0, (dw - W) / 2);
  var maxY = Math.max(0, (dh - W) / 2);
  if (_ox > maxX) _ox = maxX;
  if (_ox < -maxX) _ox = -maxX;
  if (_oy > maxY) _oy = maxY;
  if (_oy < -maxY) _oy = -maxY;
}

/* ───── Pointer/Touch обработчики ───── */
function _onPointerDown(e){
  if (e.touches && e.touches.length === 2){
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    _pinchDist = Math.sqrt(dx*dx + dy*dy);
    _drag = null;
    return;
  }
  var p = e.touches ? e.touches[0] : e;
  _drag = { x: p.clientX, y: p.clientY, ox: _ox, oy: _oy };
}
function _onPointerMove(e){
  if (e.touches && e.touches.length === 2 && _pinchDist){
    e.preventDefault();
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    var d = Math.sqrt(dx*dx + dy*dy);
    var k = d / _pinchDist;
    var ns = Math.max(_minScale, Math.min(_maxScale, _scale * k));
    _scale = ns;
    _pinchDist = d;
    _clampOffset();
    _drawPreview();
    var sl = $('avatarCropZoom'); if (sl) sl.value = String(_scale);
    return;
  }
  if (!_drag) return;
  e.preventDefault();
  var p = e.touches ? e.touches[0] : e;
  _ox = _drag.ox + (p.clientX - _drag.x);
  _oy = _drag.oy + (p.clientY - _drag.y);
  _clampOffset();
  _drawPreview();
}
function _onPointerUp(){ _drag = null; _pinchDist = null; }
function _onWheel(e){
  e.preventDefault();
  var k = e.deltaY < 0 ? 1.08 : 1/1.08;
  _scale = Math.max(_minScale, Math.min(_maxScale, _scale * k));
  _clampOffset();
  _drawPreview();
  var sl = $('avatarCropZoom'); if (sl) sl.value = String(_scale);
}

/* ───── Применить кроп → отправить на сервер ───── */
function _exportBlob(quality){
  return new Promise(function(resolve){
    var out = document.createElement('canvas');
    out.width = FINAL_SIZE;
    out.height = FINAL_SIZE;
    var octx = out.getContext('2d');
    var W = FINAL_SIZE;
    var base = Math.max(W / _img.naturalWidth, W / _img.naturalHeight);
    var s = base * _scale;
    var dw = _img.naturalWidth * s;
    var dh = _img.naturalHeight * s;
    // Пропорционально пересчитываем offset из preview-системы (PREVIEW_SIZE)
    // в финальную (FINAL_SIZE).
    var k = FINAL_SIZE / PREVIEW_SIZE;
    var dx = (W - dw) / 2 + _ox * k;
    var dy = (W - dh) / 2 + _oy * k;
    octx.fillStyle = '#000';
    octx.fillRect(0, 0, W, W);
    octx.drawImage(_img, dx, dy, dw, dh);
    out.toBlob(function(b){ resolve(b); }, 'image/jpeg', quality);
  });
}
function _blobToDataURL(blob){
  return new Promise(function(resolve, reject){
    var fr = new FileReader();
    fr.onerror = function(){ reject(new Error('FileReader')); };
    fr.onload = function(){ resolve(fr.result); };
    fr.readAsDataURL(blob);
  });
}

async function _onApply(){
  var btn = $('avatarCropApply');
  if (btn) btn.disabled = true;
  try {
    var blob = null;
    for (var i = 0; i < QUALITY_STEPS.length; i++){
      blob = await _exportBlob(QUALITY_STEPS[i]);
      if (blob && blob.size <= TARGET_BYTES) break;
    }
    if (!blob){ toast('Не удалось подготовить аватарку', 'err'); return; }
    if (blob.size > MAX_BYTES){
      toast('Файл слишком большой, выберите другое изображение', 'err');
      return;
    }
    var dataUrl = await _blobToDataURL(blob);
    var resp = await fetch('/api/auth/avatar', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ data_url: dataUrl })
    });
    var json = await resp.json().catch(function(){ return {}; });
    if (!resp.ok){
      toast((json && json.error) || 'Не удалось сохранить аватарку', 'err');
      return;
    }
    if (window.user) window.user.avatar = json.avatar || dataUrl;
    renderSidebarAvatar(window.user);
    closeCropper();
    toast('Аватарка обновлена', 'ok');
  } catch (e){
    toast('Ошибка при сохранении', 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _onReset(){
  if (window.customConfirm){
    var ok = await window.customConfirm('Сброс аватарки',
      'Вернуть стандартный аватар? Действие необратимо.');
    if (!ok) return;
  }
  try {
    var resp = await fetch('/api/auth/avatar', {
      method: 'DELETE', credentials: 'same-origin'
    });
    if (!resp.ok){ toast('Не удалось сбросить аватарку', 'err'); return; }
    if (window.user) window.user.avatar = null;
    renderSidebarAvatar(window.user);
    closeCropper();
    toast('Аватарка сброшена', 'ok');
  } catch (e){
    toast('Ошибка сети', 'err');
  }
}

/* ───── Открытие/закрытие модалки ───── */
function openAvatarCropper(file){
  fileToImage(file).then(function(img){
    _img = img;
    _scale = 1; _ox = 0; _oy = 0;
    _hasExisting = !!(window.user && window.user.avatar);
    var resetBtn = $('avatarCropReset');
    if (resetBtn) resetBtn.style.display = _hasExisting ? '' : 'none';
    var sl = $('avatarCropZoom'); if (sl) sl.value = '1';
    if (window.openModal) window.openModal('avatarCropModal');
    setTimeout(function(){
      _canvas = $('avatarCropCanvas');
      if (_canvas){
        _canvas.width = PREVIEW_SIZE;
        _canvas.height = PREVIEW_SIZE;
        _ctx = _canvas.getContext('2d');
        _drawPreview();
      }
    }, 30);
  }).catch(function(e){
    toast(e.message || 'Не удалось загрузить файл', 'err');
  });
}
function closeCropper(){
  if (window.closeModal) window.closeModal('avatarCropModal');
  _img = null; _ctx = null; _canvas = null;
  // освобождаем выбранный файл, чтобы повторный выбор того же файла сработал
  var inp = $('sbAvatarFile'); if (inp) inp.value = '';
}

/* ───── Рендер аватарки в сайдбаре ───── */
function renderSidebarAvatar(user){
  var el = $('sbAvatar');
  if (!el) return;
  if (!user){
    el.dataset.auth = '0';
    el.removeAttribute('role');
    el.removeAttribute('tabindex');
    el.removeAttribute('title');
    el.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    return;
  }
  el.dataset.auth = '1';
  el.setAttribute('role', 'button');
  el.setAttribute('tabindex', '0');
  el.setAttribute('title', 'Сменить аватарку');
  if (user.avatar){
    var safe = String(user.avatar).replace(/"/g, '&quot;');
    el.innerHTML = '<img class="sb-avatar-img" alt="" src="' + safe + '">';
  } else {
    var ch = (user.username || '?').charAt(0).toUpperCase();
    el.textContent = ch;
  }
}

/* ───── Инициализация (делегирование событий) ───── */
function _init(){
  // Клик/Enter на .sb-avatar (только когда data-auth="1")
  document.addEventListener('click', function(e){
    var t = e.target;
    while (t && t !== document){
      if (t.id === 'sbAvatar'){
        if (t.dataset && t.dataset.auth === '1'){
          var inp = $('sbAvatarFile');
          if (inp) inp.click();
        }
        return;
      }
      t = t.parentNode;
    }
  });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var el = document.activeElement;
    if (el && el.id === 'sbAvatar' && el.dataset.auth === '1'){
      e.preventDefault();
      var inp = $('sbAvatarFile');
      if (inp) inp.click();
    }
  });

  // Изменение файла → открыть кроппер
  document.addEventListener('change', function(e){
    if (!e.target || e.target.id !== 'sbAvatarFile') return;
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    if (f.size > 12 * 1024 * 1024){
      toast('Файл слишком большой (макс. 12 MB)', 'err');
      e.target.value = ''; return;
    }
    if (!/^image\/(jpeg|png|webp|gif)$/.test(f.type)){
      toast('Поддерживаются только JPEG/PNG/WebP/GIF', 'err');
      e.target.value = ''; return;
    }
    openAvatarCropper(f);
  });

  // Кнопки внутри cropper-модалки и canvas-обработчики
  document.addEventListener('click', function(e){
    var id = e.target && (e.target.id || (e.target.closest && e.target.closest('button') && e.target.closest('button').id));
    if (id === 'avatarCropApply') _onApply();
    else if (id === 'avatarCropCancel') closeCropper();
    else if (id === 'avatarCropReset') _onReset();
  });
  document.addEventListener('input', function(e){
    if (!e.target || e.target.id !== 'avatarCropZoom') return;
    _scale = Math.max(_minScale, Math.min(_maxScale, parseFloat(e.target.value) || 1));
    _clampOffset();
    _drawPreview();
  });

  // Pointer-события на canvas (вешаем при открытии модалки делегированно)
  document.addEventListener('mousedown', function(e){
    if (e.target && e.target.id === 'avatarCropCanvas') _onPointerDown(e);
  });
  document.addEventListener('mousemove', _onPointerMove);
  document.addEventListener('mouseup', _onPointerUp);
  document.addEventListener('touchstart', function(e){
    if (e.target && e.target.id === 'avatarCropCanvas') _onPointerDown(e);
  }, { passive: true });
  document.addEventListener('touchmove', function(e){
    if (e.target && e.target.id === 'avatarCropCanvas') _onPointerMove(e);
  }, { passive: false });
  document.addEventListener('touchend', _onPointerUp);
  document.addEventListener('wheel', function(e){
    if (e.target && e.target.id === 'avatarCropCanvas') _onWheel(e);
  }, { passive: false });
}

if (document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', _init);
} else { _init(); }

/* ───── G7: универсальные хелперы для отображения аватарки везде ───── */

function _esc(s){
  var d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

/* Маленькая аватарка-чип в карточках (отзывы и т.п.).
   Возвращает HTML для контейнера .review-author с аватаркой + именем + бейджем.
   - username: строка
   - avatar:   data URL или null
   - badgeHtml: уже готовый HTML бейджа (например '<span class="badge-owner">…</span>') */
function renderAuthorChip(username, avatar, badgeHtml){
  var name = _esc(username || 'user');
  var inner;
  if (avatar){
    var safe = String(avatar).replace(/"/g, '&quot;');
    inner = '<span class="author-avatar"><img class="author-avatar-img" alt="" src="' + safe + '"></span>';
  } else {
    var ch = (username || '?').charAt(0).toUpperCase();
    inner = '<span class="author-avatar author-avatar-letter">' + _esc(ch) + '</span>';
  }
  return inner + name + (badgeHtml || '');
}

/* Аватарка в шапке (topbar). Прячется, если нет авторизации.
   Клик открывает сайдбар (toggleSidebar). */
function renderTopbarAvatar(user){
  var el = document.getElementById('topbarAvatar');
  if (!el) return;
  if (!user){
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  el.style.display = '';
  if (user.avatar){
    var safe = String(user.avatar).replace(/"/g, '&quot;');
    el.innerHTML = '<img class="topbar-avatar-img" alt="" src="' + safe + '">';
  } else {
    el.textContent = (user.username || '?').charAt(0).toUpperCase();
  }
}

window.openAvatarCropper = openAvatarCropper;
window.closeAvatarCropper = closeCropper;
window.renderSidebarAvatar = renderSidebarAvatar;
window.renderAuthorChip = renderAuthorChip;
window.renderTopbarAvatar = renderTopbarAvatar;
