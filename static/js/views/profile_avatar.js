/* views/profile_avatar.js — T10: расширенная аватарка (фото / GIF / видео ≤10с).

   Полностью vanilla, без сторонних библиотек. Логика:

   1. Клик по .sb-avatar (data-auth="1") → скрытый <input type=file accept=…>.
   2. По выбранному файлу определяем kind:
      - image/jpeg|png|webp → старый кроп-канвас 256×256 (модалка
        avatarCropModal) → POST /api/auth/avatar/upload (multipart,
        kind=image).
      - image/gif → без кропа, как есть → POST upload (kind=gif).
      - video/mp4|webm|quicktime → off-screen <video> для определения
        длительности → модалка videoTrimModal с двумя ползунками
        (clip_start / clip_end, диапазон ≤10с, авто-loop предпросмотр)
        → POST upload (kind=video, clip_start, clip_end).
   3. После сохранения — обновляем window.user.avatar_media и
      перерисовываем все аватарки через renderAvatarMedia / renderSidebarAvatar.

   Все строки на русском (правило проекта). Эмодзи запрещены.
*/

/* ───── Константы (синхронизированы с freeapi/config.py) ───── */
var IMG_TARGET_BYTES = 180 * 1024;  // целевой размер JPEG-кропа
var IMG_MAX_BYTES = 1 * 1024 * 1024;
var GIF_MAX_BYTES = 3 * 1024 * 1024;
var VIDEO_MAX_BYTES = 6 * 1024 * 1024;
var VIDEO_MAX_DURATION = 10.0;
var QUALITY_STEPS = [0.92, 0.85, 0.78];
var FINAL_SIZE = 256;
var PREVIEW_SIZE = 320;

/* ───── Состояние кропа ───── */
var _img = null;
var _scale = 1;
var _minScale = 1;
var _maxScale = 8;
var _ox = 0, _oy = 0;
var _drag = null;
var _pinchDist = null;
var _canvas = null;
var _ctx = null;
var _hasExisting = false;

/* ───── Состояние видеоредактора ───── */
var _vidFile = null;
var _vidDuration = 0;
var _vidStart = 0;
var _vidEnd = 0;
var _vidPreviewEl = null;
var _vidTimeUpd = null;

/* ───── Утилиты ───── */
function $(id){ return document.getElementById(id); }
function toast(msg, type){ if (window.showToast) window.showToast(msg, type); }
function _esc(s){
  var d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}
function _fmtSec(s){
  if (!isFinite(s)) return '0.0';
  return (Math.round(s * 10) / 10).toFixed(1);
}
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
function fileToVideoMeta(file){
  return new Promise(function(resolve, reject){
    var url = URL.createObjectURL(file);
    var v = document.createElement('video');
    v.preload = 'metadata';
    v.muted = true;
    v.playsInline = true;
    v.onloadedmetadata = function(){
      var d = isFinite(v.duration) ? v.duration : 0;
      resolve({ url: url, duration: d, video: v });
    };
    v.onerror = function(){
      URL.revokeObjectURL(url);
      reject(new Error('Не удалось прочитать видео'));
    };
    v.src = url;
  });
}

/* ───── КАДРИРОВАНИЕ ИЗОБРАЖЕНИЯ ───── */
function _drawPreview(){
  if (!_ctx || !_img) return;
  var W = PREVIEW_SIZE, H = PREVIEW_SIZE;
  _ctx.clearRect(0, 0, W, H);
  _ctx.fillStyle = '#000';
  _ctx.fillRect(0, 0, W, H);
  var base = Math.max(W / _img.naturalWidth, H / _img.naturalHeight);
  var s = base * _scale;
  var dw = _img.naturalWidth * s;
  var dh = _img.naturalHeight * s;
  var dx = (W - dw) / 2 + _ox;
  var dy = (H - dh) / 2 + _oy;
  _ctx.drawImage(_img, dx, dy, dw, dh);
  _ctx.strokeStyle = 'rgba(255,255,255,.55)';
  _ctx.lineWidth = 2;
  _ctx.strokeRect(1, 1, W - 2, H - 2);
}
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
    _scale = Math.max(_minScale, Math.min(_maxScale, _scale * k));
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
    var k = FINAL_SIZE / PREVIEW_SIZE;
    var dx = (W - dw) / 2 + _ox * k;
    var dy = (W - dh) / 2 + _oy * k;
    octx.fillStyle = '#000';
    octx.fillRect(0, 0, W, W);
    octx.drawImage(_img, dx, dy, dw, dh);
    out.toBlob(function(b){ resolve(b); }, 'image/jpeg', quality);
  });
}

/* ───── Универсальная отправка multipart-ом ───── */
async function _uploadMedia(blob, kind, extras){
  var fd = new FormData();
  fd.append('file', blob, 'avatar.' + (
    kind === 'gif' ? 'gif' :
    kind === 'video' ? (blob.type && blob.type.indexOf('webm') >= 0 ? 'webm' : 'mp4') :
    'jpg'
  ));
  fd.append('kind', kind);
  if (extras){
    for (var k in extras){
      if (Object.prototype.hasOwnProperty.call(extras, k)){
        fd.append(k, String(extras[k]));
      }
    }
  }
  var resp = await fetch('/api/auth/avatar/upload', {
    method: 'POST',
    credentials: 'same-origin',
    body: fd
  });
  var json = await resp.json().catch(function(){ return {}; });
  if (!resp.ok){
    throw new Error((json && json.error) || ('HTTP ' + resp.status));
  }
  return json.avatar_media || null;
}

async function _onApply(){
  var btn = $('avatarCropApply');
  if (btn) btn.disabled = true;
  try {
    var blob = null;
    for (var i = 0; i < QUALITY_STEPS.length; i++){
      blob = await _exportBlob(QUALITY_STEPS[i]);
      if (blob && blob.size <= IMG_TARGET_BYTES) break;
    }
    if (!blob){ toast('Не удалось подготовить аватарку', 'err'); return; }
    if (blob.size > IMG_MAX_BYTES){
      toast('Файл слишком большой, выберите другое изображение', 'err');
      return;
    }
    var media = await _uploadMedia(blob, 'image', null);
    _onMediaSaved(media);
    closeCropper();
    toast('Аватарка обновлена', 'ok');
  } catch (e){
    toast(e.message || 'Ошибка при сохранении', 'err');
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
    if (window.user){ window.user.avatar = null; window.user.avatar_media = null; }
    renderSidebarAvatar(window.user);
    closeCropper();
    closeVideoTrimmer();
    toast('Аватарка сброшена', 'ok');
  } catch (e){
    toast('Ошибка сети', 'err');
  }
}

function _onMediaSaved(media){
  if (window.user){
    window.user.avatar_media = media || null;
    // Затираем legacy data URL — фронт всё равно теперь смотрит avatar_media.
    window.user.avatar = null;
  }
  renderSidebarAvatar(window.user);
}

/* ───── Кроп-модалка (image) ───── */
function openAvatarCropper(file){
  fileToImage(file).then(function(img){
    _img = img;
    _scale = 1; _ox = 0; _oy = 0;
    _hasExisting = !!(window.user && (window.user.avatar || window.user.avatar_media));
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
  var inp = $('sbAvatarFile'); if (inp) inp.value = '';
}

/* ───── GIF: загрузка as-is, без обрезки ───── */
async function _uploadGifAsIs(file){
  if (file.size > GIF_MAX_BYTES){
    toast('GIF слишком большой (макс. ' + Math.floor(GIF_MAX_BYTES/1024/1024) + ' МБ)', 'err');
    return;
  }
  try {
    var media = await _uploadMedia(file, 'gif', null);
    _onMediaSaved(media);
    toast('GIF-аватарка обновлена', 'ok');
  } catch (e){
    toast(e.message || 'Ошибка при загрузке GIF', 'err');
  } finally {
    var inp = $('sbAvatarFile'); if (inp) inp.value = '';
  }
}

/* ───── Видеоредактор: модалка videoTrimModal ───── */
function openVideoTrimmer(file){
  if (file.size > VIDEO_MAX_BYTES){
    toast('Видео слишком большое (макс. ' + Math.floor(VIDEO_MAX_BYTES/1024/1024) + ' МБ)', 'err');
    var inp = $('sbAvatarFile'); if (inp) inp.value = '';
    return;
  }
  fileToVideoMeta(file).then(function(meta){
    _vidFile = file;
    _vidDuration = meta.duration || 0;
    if (_vidDuration <= 0){
      toast('Не удалось определить длительность видео', 'err');
      return;
    }
    // Стартовый диапазон: первые VIDEO_MAX_DURATION секунд (или весь ролик).
    _vidStart = 0;
    _vidEnd = Math.min(_vidDuration, VIDEO_MAX_DURATION);

    if (window.openModal) window.openModal('videoTrimModal');
    setTimeout(function(){ _setupVideoTrimmerUI(meta.url); }, 30);
  }).catch(function(e){
    toast(e.message || 'Не удалось открыть видео', 'err');
    var inp = $('sbAvatarFile'); if (inp) inp.value = '';
  });
}

function _setupVideoTrimmerUI(blobUrl){
  var prev = $('videoTrimPreview');
  var sStart = $('videoTrimStart');
  var sEnd = $('videoTrimEnd');
  var lblStart = $('videoTrimStartLbl');
  var lblEnd = $('videoTrimEndLbl');
  var lblDur = $('videoTrimDurLbl');
  var lblTotal = $('videoTrimTotalLbl');
  if (!prev || !sStart || !sEnd) return;

  // Освобождаем старый src, если был
  if (_vidPreviewEl && _vidPreviewEl.src){
    try { URL.revokeObjectURL(_vidPreviewEl.src); } catch(_){}
  }
  _vidPreviewEl = prev;
  prev.src = blobUrl;
  prev.muted = true;
  prev.playsInline = true;
  prev.loop = false;  // loop делаем через timeupdate — HTML5 loop игнорирует #t
  prev.controls = false;

  var step = 0.05;
  sStart.min = '0';
  sStart.max = String(_vidDuration);
  sStart.step = String(step);
  sStart.value = String(_vidStart);
  sEnd.min = '0';
  sEnd.max = String(_vidDuration);
  sEnd.step = String(step);
  sEnd.value = String(_vidEnd);

  function refreshLabels(){
    if (lblStart) lblStart.textContent = _fmtSec(_vidStart) + ' с';
    if (lblEnd)   lblEnd.textContent   = _fmtSec(_vidEnd)   + ' с';
    if (lblDur)   lblDur.textContent   = _fmtSec(_vidEnd - _vidStart) + ' с';
    if (lblTotal) lblTotal.textContent = _fmtSec(_vidDuration) + ' с';
  }
  refreshLabels();

  // Обработчик выхода за clip_end → перемотать на clip_start (loop по диапазону).
  if (_vidTimeUpd) prev.removeEventListener('timeupdate', _vidTimeUpd);
  _vidTimeUpd = function(){
    if (prev.currentTime >= _vidEnd - 0.03 || prev.currentTime < _vidStart - 0.03){
      try { prev.currentTime = _vidStart; } catch(_){}
    }
  };
  prev.addEventListener('timeupdate', _vidTimeUpd);

  prev.currentTime = _vidStart;
  prev.play().catch(function(){});

  function onStartInput(){
    var v = parseFloat(sStart.value) || 0;
    if (v < 0) v = 0;
    if (v > _vidDuration - 0.1) v = _vidDuration - 0.1;
    _vidStart = v;
    if (_vidEnd <= _vidStart + 0.1){
      _vidEnd = Math.min(_vidDuration, _vidStart + 0.1);
      sEnd.value = String(_vidEnd);
    }
    if (_vidEnd - _vidStart > VIDEO_MAX_DURATION){
      _vidEnd = Math.min(_vidDuration, _vidStart + VIDEO_MAX_DURATION);
      sEnd.value = String(_vidEnd);
    }
    refreshLabels();
    try { prev.currentTime = _vidStart; } catch(_){}
  }
  function onEndInput(){
    var v = parseFloat(sEnd.value) || 0;
    if (v > _vidDuration) v = _vidDuration;
    if (v < _vidStart + 0.1) v = _vidStart + 0.1;
    if (v - _vidStart > VIDEO_MAX_DURATION){
      v = _vidStart + VIDEO_MAX_DURATION;
    }
    _vidEnd = v;
    refreshLabels();
  }
  sStart.oninput = onStartInput;
  sEnd.oninput = onEndInput;
}

function closeVideoTrimmer(){
  if (window.closeModal) window.closeModal('videoTrimModal');
  if (_vidPreviewEl){
    try { _vidPreviewEl.pause(); } catch(_){}
    if (_vidTimeUpd) _vidPreviewEl.removeEventListener('timeupdate', _vidTimeUpd);
    if (_vidPreviewEl.src){
      try { URL.revokeObjectURL(_vidPreviewEl.src); } catch(_){}
    }
    _vidPreviewEl.removeAttribute('src');
    _vidPreviewEl.load && _vidPreviewEl.load();
  }
  _vidPreviewEl = null;
  _vidTimeUpd = null;
  _vidFile = null;
  _vidDuration = 0;
  _vidStart = 0;
  _vidEnd = 0;
  var inp = $('sbAvatarFile'); if (inp) inp.value = '';
}

async function _onVideoApply(){
  var btn = $('videoTrimApply');
  if (btn) btn.disabled = true;
  try {
    if (!_vidFile){ toast('Видео не выбрано', 'err'); return; }
    if (_vidEnd - _vidStart <= 0.05){
      toast('Слишком короткий фрагмент', 'err'); return;
    }
    if (_vidEnd - _vidStart > VIDEO_MAX_DURATION + 0.05){
      toast('Максимум ' + VIDEO_MAX_DURATION + ' секунд', 'err'); return;
    }
    var media = await _uploadMedia(_vidFile, 'video', {
      clip_start: _fmtSec(_vidStart),
      clip_end:   _fmtSec(_vidEnd)
    });
    _onMediaSaved(media);
    closeVideoTrimmer();
    toast('Видео-аватарка обновлена', 'ok');
  } catch (e){
    toast(e.message || 'Ошибка при сохранении видео', 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ───── Универсальный рендер медиа-аватарки ───── */

/* Нормализация: legacy avatar (data URL) + новое avatar_media → единый dict
   { kind: 'image'|'gif'|'video', url, clip_start, clip_end } или null. */
function _normalizeMedia(mediaOrLegacy){
  if (!mediaOrLegacy) return null;
  if (typeof mediaOrLegacy === 'string'){
    return { kind: 'image', url: mediaOrLegacy, clip_start: null, clip_end: null };
  }
  if (typeof mediaOrLegacy === 'object' && mediaOrLegacy.url && mediaOrLegacy.kind){
    return mediaOrLegacy;
  }
  return null;
}

/* Рендер в произвольный контейнер.
   container — DOM-элемент (innerHTML будет полностью заменён).
   media — { kind, url, clip_start, clip_end } или null.
   opts:
     imgClass / videoClass — CSS-классы для <img>/<video>.
     letter — буква для пустого состояния (или null = ничего не рисовать).
     letterClass — CSS-класс для элемента с буквой.
*/
function renderAvatarMedia(container, media, opts){
  if (!container) return;
  opts = opts || {};
  media = _normalizeMedia(media);

  if (!media){
    if (opts.letter != null){
      var lc = opts.letterClass ? (' class="' + _esc(opts.letterClass) + '"') : '';
      container.innerHTML = '<span' + lc + '>' + _esc(opts.letter) + '</span>';
    } else {
      container.innerHTML = '';
    }
    return;
  }

  var safeUrl = String(media.url).replace(/"/g, '&quot;');

  if (media.kind === 'video'){
    var cs = isFinite(media.clip_start) ? Number(media.clip_start) : 0;
    var ce = isFinite(media.clip_end) ? Number(media.clip_end) : (cs + VIDEO_MAX_DURATION);
    var fragUrl = safeUrl + '#t=' + cs.toFixed(2) + ',' + ce.toFixed(2);
    var vClass = opts.videoClass || 'avatar-media-video';
    container.innerHTML =
      '<video class="' + _esc(vClass) + '" src="' + fragUrl + '" ' +
      'autoplay muted playsinline preload="auto" disablepictureinpicture></video>';
    var v = container.querySelector('video');
    if (v){
      v.addEventListener('loadedmetadata', function(){
        try { v.currentTime = cs; } catch(_){}
        v.play().catch(function(){});
      });
      v.addEventListener('timeupdate', function(){
        if (v.currentTime >= ce - 0.03 || v.currentTime < cs - 0.03){
          try { v.currentTime = cs; } catch(_){}
        }
      });
    }
    return;
  }

  // image / gif → одинаково как <img>
  var iClass = opts.imgClass || 'avatar-media-img';
  container.innerHTML =
    '<img class="' + _esc(iClass) + '" alt="" src="' + safeUrl + '">';
}

/* Рендер аватарки в сайдбаре (с обработкой не-авторизованного состояния). */
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
  var media = user.avatar_media || (user.avatar ? user.avatar : null);
  var letter = (user.username || '?').charAt(0).toUpperCase();
  renderAvatarMedia(el, media, {
    imgClass: 'sb-avatar-img',
    videoClass: 'sb-avatar-video',
    letter: letter,
    letterClass: ''
  });
  // Если буквы — innerHTML стал <span>letter</span>, но мы хотим просто
  // textContent для совместимости со старым CSS .sb-avatar:not(:has(img)) —
  // переписываем без <span>-обёртки.
  if (!media){
    el.textContent = letter;
  }
}

/* Маленькая аватарка-чип в карточках (отзывы и т.п.).
   Возвращает HTML-строку: <span.author-avatar>(media or letter)</span> + name + badge.

   Backwards-compat: 2-й аргумент может быть строкой (старый avatar URL),
   объектом {kind,url,...} или null. */
function renderAuthorChip(username, mediaOrAvatar, badgeHtml){
  var name = _esc(username || 'user');
  var media = _normalizeMedia(mediaOrAvatar);
  var inner;
  if (media && media.kind === 'video'){
    var cs = isFinite(media.clip_start) ? Number(media.clip_start) : 0;
    var ce = isFinite(media.clip_end) ? Number(media.clip_end) : (cs + VIDEO_MAX_DURATION);
    var fragUrl = String(media.url).replace(/"/g, '&quot;') +
      '#t=' + cs.toFixed(2) + ',' + ce.toFixed(2);
    inner = '<span class="author-avatar">' +
      '<video class="author-avatar-video" src="' + fragUrl + '" ' +
      'autoplay muted playsinline preload="auto" loop ' +
      'data-clip-start="' + cs.toFixed(2) + '" ' +
      'data-clip-end="' + ce.toFixed(2) + '" disablepictureinpicture></video>' +
    '</span>';
  } else if (media){
    var safe = String(media.url).replace(/"/g, '&quot;');
    inner = '<span class="author-avatar"><img class="author-avatar-img" alt="" src="' + safe + '"></span>';
  } else {
    var ch = (username || '?').charAt(0).toUpperCase();
    inner = '<span class="author-avatar author-avatar-letter">' + _esc(ch) + '</span>';
  }
  return inner + name + (badgeHtml || '');
}

/* Делегированный «petlevoy» обработчик для всех <video data-clip-start data-clip-end>,
   рождённых через innerHTML-вставку (renderAuthorChip / community-msg-avatar и т.п.).
   Стандартный atom #t=start,end не уважает loop, поэтому мы централизованно
   перематываем currentTime на clip_start при выходе за clip_end. */
function _initLoopedVideos(){
  document.addEventListener('timeupdate', function(e){
    var v = e.target;
    if (!v || v.tagName !== 'VIDEO') return;
    var cs = parseFloat(v.dataset.clipStart);
    var ce = parseFloat(v.dataset.clipEnd);
    if (!isFinite(cs) || !isFinite(ce)) return;
    if (v.currentTime >= ce - 0.03 || v.currentTime < cs - 0.03){
      try { v.currentTime = cs; } catch(_){}
    }
  }, true);
}

/* ───── Инициализация (делегирование событий) ───── */
function _init(){
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

  // Изменение файла → определяем kind и открываем нужный редактор.
  document.addEventListener('change', function(e){
    if (!e.target || e.target.id !== 'sbAvatarFile') return;
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    if (f.size > 12 * 1024 * 1024){
      toast('Файл слишком большой (макс. 12 МБ)', 'err');
      e.target.value = ''; return;
    }
    var t = (f.type || '').toLowerCase();
    if (t === 'image/gif'){
      _uploadGifAsIs(f);
    } else if (/^image\/(jpeg|png|webp)$/.test(t)){
      openAvatarCropper(f);
    } else if (/^video\/(mp4|webm|quicktime)$/.test(t)){
      openVideoTrimmer(f);
    } else {
      toast('Поддерживаются JPEG, PNG, WebP, GIF, MP4, WebM', 'err');
      e.target.value = '';
    }
  });

  // Кнопки cropper-модалки.
  document.addEventListener('click', function(e){
    var node = e.target;
    var id = node && (node.id || (node.closest && node.closest('button') && node.closest('button').id));
    if (id === 'avatarCropApply') _onApply();
    else if (id === 'avatarCropCancel') closeCropper();
    else if (id === 'avatarCropReset') _onReset();
    else if (id === 'videoTrimApply') _onVideoApply();
    else if (id === 'videoTrimCancel') closeVideoTrimmer();
    else if (id === 'videoTrimReset') _onReset();
  });
  document.addEventListener('input', function(e){
    if (!e.target || e.target.id !== 'avatarCropZoom') return;
    _scale = Math.max(_minScale, Math.min(_maxScale, parseFloat(e.target.value) || 1));
    _clampOffset();
    _drawPreview();
  });

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

  _initLoopedVideos();
}

if (document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', _init);
} else { _init(); }

window.openAvatarCropper = openAvatarCropper;
window.closeAvatarCropper = closeCropper;
window.openVideoTrimmer = openVideoTrimmer;
window.closeVideoTrimmer = closeVideoTrimmer;
window.renderSidebarAvatar = renderSidebarAvatar;
window.renderAuthorChip = renderAuthorChip;
window.renderAvatarMedia = renderAvatarMedia;
