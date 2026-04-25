/* views/keys.js — кабинет: dashboard, список ключей, действия с ключами,
   настройки ключа, история запросов.
   Шаг 0.5b: вынесено из inline-скрипта static/index.html.

   Setup-функции (импорт сессии, прогресс настройки, raw-key copy для setup)
   ОСТАВЛЕНЫ в inline — они идут отдельным шагом 0.5c (setup.js).

   Зависимости (выставлены до этого файла):
   window.api, window.q, window.esc, window.openModal, window.closeModal,
   window.showToast, window.customConfirm, window.goView,
   window.buildCustomSelect, window.refreshNotifBadge, window.updateSidebarTg,
   window.openChatWithKey, window.downloadKeySession.
   Глобальные state: window.user, window.accountState, window.allKeys,
   window.allModels, window.currentKeyId, window._forceSetupFlowVisible,
   window.sseSource, window.setupId, window._tfaCode. */

(function(){
  function _q(id){ return document.getElementById(id); }
  function _esc(s){ return window.esc ? window.esc(s) : String(s == null ? '' : s); }

  /* ───────────── DASHBOARD ───────────── */
  function loadDashboard(){
    loadSideStats();
    updateTgStatus();
    if (window.refreshNotifBadge) window.refreshNotifBadge();
    window.api('/api/keys').then(function(d){
      var keys = d.keys || [];
      window.allKeys = keys;
      renderKeys(keys);
      // Привязка Telegram — опциональна. Кнопка «Новый ключ» видна всегда;
      // модалку настройки открываем ТОЛЬКО по явному клику пользователя.
      // Никаких авто-попапов после входа/регистрации больше нет.
      _q('btnNewKey').style.display = '';
    });
  }

  function _isSetupModalOpen(){
    var m = _q('setupModal');
    return !!(m && m.classList && m.classList.contains('open'));
  }

  /* TG Status — F-06: статус Telegram-аккаунта.
     Сама плашка #tgStatusBar по требованию убрана с дашборда; сейчас этот
     метод нужен только для обновления window.accountState и для
     updateSidebarTg() (значок в сайдбаре). DOM-элемента tgStatusBar в HTML
     больше нет, поэтому НИЧЕГО не пишем в него. */
  function updateTgStatus(){
    window.api('/api/auth/me').then(function(d){
      window.accountState = d || null;
      if (typeof window.updateSidebarTg === 'function') window.updateSidebarTg();
    }).catch(function(){});
  }

  function loadSideStats(){
    window.api('/api/stats/global').then(function(d){
      _q('dUsers').textContent = (d.users || 0).toLocaleString('ru-RU');
      _q('dToday').textContent = (d.todayRequests || 0).toLocaleString('ru-RU');
    }).catch(function(){});
    window.api('/api/models').then(function(d){
      var models = d.models || [];
      var sorted = models.slice().sort(function(a, b){ return (b.totalRequests || 0) - (a.totalRequests || 0); }).slice(0, 4);
      _q('sideModelsList').innerHTML = sorted.map(function(m){
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid #0a0a0a"><span style="font-size:12px;color:#555;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">' + _esc(m.displayName) + '</span><span style="font-size:11px;color:#555;flex-shrink:0;margin-left:8px">' + (m.totalRequests || 0) + '</span></div>';
      }).join('') || '<div style="font-size:12px;color:#555;padding:4px 0">Нет данных</div>';
    }).catch(function(){});
  }

  /* ───────────── KEYS ───────────── */
  function renderKeys(keys){
    var list = _q('keysList');
    if (!keys.length) {
      list.innerHTML = '<div class="key-empty"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg><p>Ключей пока нет</p><small>Когда захотите получить API-ключ — нажмите «Новый ключ» и подключите Telegram-аккаунт. Все остальные разделы доступны и без привязки.</small></div>';
      return;
    }
    list.innerHTML = '';
    keys.forEach(function(k){
      var div = document.createElement('div');
      div.className = 'key-card';
      div.innerHTML =
      '<div class="key-head">' +
        '<div class="key-name"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>' + _esc(k.name || 'Ключ') + '</div>' +
        '<div class="key-acts">' +
          '<button class="btn btn-icon" title="Открыть чат" onclick="openChatWithKey(\'' + k.id + '\',\'' + _esc(k.name) + '\',\'' + _esc(k.default_model || '') + '\',\'' + _esc(k.keyValue || k.key_value || '') + '\')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>' +
          '<button class="btn btn-icon" title="Скачать сессию" onclick="downloadKeySession(\'' + k.id + '\',\'' + _esc(k.name) + '\')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></button>' +
          '<button class="btn btn-icon" title="История запросов" onclick="showHistory(\'' + k.id + '\',\'' + _esc(k.name) + '\')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></button>' +
          '<button class="btn btn-icon" title="Настройки" onclick="openKeySettings(\'' + k.id + '\',\'' + _esc(k.name) + '\',\'' + _esc(k.default_model) + '\',' + (k.skip_hints || 0) + ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg></button>' +
          '<button class="btn btn-icon" title="Скопировать ключ" onclick="copyKeyVal(\'' + _esc(k.key_value || k.keyValue || '') + '\',this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>' +
          '<button class="btn btn-icon" title="Перегенерировать" onclick="regenKey(\'' + k.id + '\',this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>' +
          '<button class="btn btn-icon btn-icon-danger" title="Удалить" onclick="deleteKey(\'' + k.id + '\',this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>' +
        '</div>' +
      '</div>' +
      '<div class="key-val"><div class="key-val-text">' + _esc(k.keyValue || k.key_value || '') + '</div><button class="btn btn-icon" title="Скопировать ключ" onclick="copyKeyVal(\'' + _esc(k.key_value || k.keyValue || '') + '\',this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button></div>' +
      '<div class="key-foot">' +
        '<div class="key-model"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/></svg>' + _esc(k.default_model || '—') + '</div>' +
        (k.dual_mode ? '<div class="key-stat" title="Dual-режим: EN экономия токенов"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>EN</div>' : '') +
        (k.mainAccountInfo && ((k.mainAccountInfo.username || '') || (k.mainAccountInfo.firstName || '')) ? '<div class="key-stat" title="Telegram-аккаунт ключа"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6z"/><polyline points="22 10 12 17 2 10"/></svg>' + _esc(k.mainAccountInfo.username ? ('@' + k.mainAccountInfo.username) : k.mainAccountInfo.firstName) + '</div>' : '') +
        (k.context_kb > 0 ? '<div class="key-stat" title="Размер контекста"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>' + parseFloat(k.context_kb || 0).toFixed(1) + ' KB</div>' : '') +
        '<div class="key-stat"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>' + ((k.monthlyRequests || 0) + ' мес.') + '</div>' +
        '<div class="key-stat"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' + ((k.avgResponseMs || 0) + ' мс') + '</div>' +
      '</div>';
      list.appendChild(div);
    });
  }

  function copyKeyVal(val, btn){
    if (!val) {
      window.showToast('Нет значения для копирования', 'err');
      return;
    }
    navigator.clipboard.writeText(val).then(function(){
      var orig = btn.innerHTML;
      btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
      setTimeout(function(){ btn.innerHTML = orig; }, 1800);
      window.showToast('Ключ скопирован', 'ok');
    });
  }

  function regenKey(id, btn){
    btn.disabled = true;
    window.api('/api/keys/' + id + '/regen', 'POST').then(function(d){
      if (d.error) { window.showToast(d.message || 'Ошибка регенерации', 'err'); return; }
      // F-01: показать rawKey в модалке
      if (d.key && d.key.rawKey) {
        _q('rawKeyDisplay').textContent = d.key.rawKey;
        if (window.openModal) window.openModal('rawKeyModal');
      }
      loadDashboard();
    }).finally(function(){ btn.disabled = false; });
  }

  function deleteKey(id, btn){
    window.customConfirm('Удаление ключа', 'Удалить этот ключ? Действие необратимо.').then(function(ok){
      if (!ok) return;
      btn.disabled = true;
      window.api('/api/keys/' + id, 'DELETE')
        .then(function(){ loadDashboard(); window.showToast('Ключ удалён', 'ok'); })
        .finally(function(){ btn.disabled = false; });
    });
  }

  /* Сброс полей и запуск модалки настройки. Используется и для авто-открытия
     при пустом списке ключей, и для кнопки «Новый ключ». */
  function _openSetupModalFresh(){
    window._forceSetupFlowVisible = true;
    if (window.sseSource) { window.sseSource.close(); window.sseSource = null; }
    window.setupId = null;
    window._tfaCode = null;
    if (_q('setupFormCard'))     _q('setupFormCard').style.display = '';
    if (_q('setupProgressCard')) _q('setupProgressCard').style.display = 'none';
    if (_q('setupErr'))          _q('setupErr').textContent = '';
    if (_q('progErr'))          { _q('progErr').style.display = 'none'; _q('progErr').textContent = ''; }
    if (_q('progSuccess'))       _q('progSuccess').style.display = 'none';
    if (_q('progKey'))           _q('progKey').textContent = '';
    if (_q('codeInputWrap'))     _q('codeInputWrap').style.display = 'none';
    if (_q('codeInput'))         _q('codeInput').value = '';
    if (_q('codeErr'))           _q('codeErr').textContent = '';
    if (_q('sPhone'))            _q('sPhone').value = '';
    if (_q('sSession'))          _q('sSession').value = '';
    if (_q('btnSetup'))         { _q('btnSetup').disabled = false; _q('btnSetup').textContent = 'Запустить настройку'; }
    if (window.openModal) window.openModal('setupModal');
  }

  function createKey(){
    window._setupModalDismissed = false;
    _openSetupModalFresh();
    window.showToast('Введите данные нового Telegram-аккаунта — ключ создастся после завершения настройки', 'ok');
  }

  /* Закрытие модалки. Если в этой сессии у юзера уже есть ключи — просто
     закрываем; если ключей нет, ставим флаг _setupModalDismissed, чтобы
     loadDashboard() её не открывал заново автоматически до перезагрузки. */
  function closeSetupModal(){
    window._setupModalDismissed = true;
    window._forceSetupFlowVisible = false;
    if (window.closeModal) window.closeModal('setupModal');
  }
  window.closeSetupModal = closeSetupModal;

  /* Raw key copy — F-01 (используется в модалке после регенерации). */
  function copyRawKey(){
    var val = _q('rawKeyDisplay').textContent;
    navigator.clipboard.writeText(val).then(function(){
      var btn = _q('rawKeyCopyBtn');
      btn.textContent = 'Скопировано!';
      setTimeout(function(){ btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Скопировать ключ'; }, 2000);
      window.showToast('Ключ скопирован', 'ok');
    });
  }

  function closeRawKeyModal(goDash){
    if (window.closeModal) window.closeModal('rawKeyModal');
    _q('rawKeyDashBtn').style.display = 'none';
    _q('rawKeyModalTitle').textContent = 'Ключ перегенерирован';
    _q('rawKeyModalSub').textContent = 'Сохраните ключ — после закрытия он будет скрыт';
    if (goDash) {
      loadDashboard();
      if (_q('setupProgressCard')) _q('setupProgressCard').style.display = 'none';
      if (window.closeModal) window.closeModal('setupModal');
    }
  }

  /* ───────────── KEY SETTINGS ───────────── */
  function openKeySettings(id, name, model, skipHints){
    window.currentKeyId = id;
    _q('ksKeyId').value = id;
    _q('ksKeyName').textContent = name || 'Ключ';
    _q('ksName').value = name || '';
    _q('ksSkipHints').checked = !!skipHints;
    _q('ksErr').textContent = '';
    _q('ksModelWarn').style.display = 'none';
    _q('ksDualMode').checked = false;
    _q('ksDualTranslatorWrap').style.display = 'none';
    var sel = _q('ksModel');
    sel.innerHTML = (window.allModels || []).map(function(m){
      return '<option value="' + _esc(m.id) + '"' + (m.id === model ? ' selected' : '') + '>' + _esc(m.displayName) + '</option>';
    }).join('');
    var origModel = model;
    sel.onchange = function(){ _q('ksModelWarn').style.display = sel.value !== origModel ? '' : 'none'; };
    var key = window.allKeys ? window.allKeys.find(function(k){ return k.id === id; }) : null;
    if (key) {
      _q('ksDualMode').checked = !!(key.dual_mode);
      _q('ksDualTranslatorWrap').style.display = key.dual_mode ? '' : 'none';
      window.api('/api/keys').then(function(d){
        var allAccKeys = d.keys || [];
        var otherAccounts = allAccKeys.filter(function(k2){ return k2.tg_account_id && k2.tg_account_id !== key.tg_account_id && k2.setup_done; });
        var transOpts;
        if (otherAccounts.length === 0) {
          transOpts = [{ value: '', label: '— Нет готовых аккаунтов —' }];
        } else {
          transOpts = otherAccounts.map(function(k2){
            return { value: k2.tg_account_id || '', label: k2.tg_username || k2.name || String(k2.id) };
          });
        }
        if (window.buildCustomSelect) window.buildCustomSelect('ksDualTranslatorSelect', transOpts, key.translator_account_id || '');
      }).catch(function(){});
    }
    if (window.openModal) window.openModal('keySettingsModal');
  }

  function onKsDualModeChange(){
    var checked = _q('ksDualMode').checked;
    _q('ksDualTranslatorWrap').style.display = checked ? '' : 'none';
  }

  function saveKeySettings(e){
    e.preventDefault();
    var btn = _q('ksBtn'), err = _q('ksErr');
    err.textContent = ''; btn.disabled = true; btn.textContent = 'Сохранение...';
    var id = _q('ksKeyId').value;
    var dual = _q('ksDualMode').checked;
    var _trInput = _q('ksDualTranslatorVal');
    var trId = dual ? (_trInput ? _trInput.value : '') : null;
    window.api('/api/keys/' + id, 'PUT', {
      name: _q('ksName').value.trim(),
      defaultModel: _q('ksModel').value,
      skipHints: _q('ksSkipHints').checked,
      dualMode: dual,
      translatorAccountId: trId || null,
    }).then(function(d){
      if (d.error) { err.textContent = d.message || 'Ошибка'; return; }
      if (window.closeModal) window.closeModal('keySettingsModal');
      loadDashboard();
      window.showToast('Настройки ключа сохранены', 'ok');
    }).catch(function(){ err.textContent = 'Ошибка сети'; })
    .finally(function(){ btn.disabled = false; btn.textContent = 'Сохранить изменения'; });
  }

  /* ───────────── HISTORY ───────────── */
  function showHistory(id, name){
    _q('histTitle').textContent = 'История: ' + (name || 'ключ');
    _q('histSub').textContent = '';
    _q('histList').innerHTML = '<div class="hist-empty">Загрузка...</div>';
    if (window.goView) window.goView('history');
    window.api('/api/keys/' + id).then(function(d){
      var logs = d.logs || [];
      _q('histSub').textContent = logs.length + ' запрос(ов) за всё время (последние 50)';
      if (!logs.length) {
        // F-07: информативный empty state с примером curl-запроса.
        var keyVal = d.key && d.key.key_value ? d.key.key_value : 'fa_sk_your_key';
        _q('histList').innerHTML =
          '<div class="hist-empty">' +
            '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin:0 auto 12px;display:block;color:#1a1a1a"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>' +
            '<div style="margin-bottom:16px;color:#666;font-size:13px">Запросов ещё не было. Сделайте первый:</div>' +
            '<div style="background:#080808;border:1px solid #141414;border-radius:10px;padding:14px;text-align:left;font-family:JetBrains Mono,monospace;font-size:11px;color:#777;line-height:1.9;word-break:break-all">' +
              '<span style="color:#666">curl</span> <span style="color:#888">-X POST</span> /api/v1/chat \\\n' +
              '  <span style="color:#888">-H</span> <span style="color:#777">"Authorization: Bearer ' + _esc(keyVal) + '"</span> \\\n' +
              '  <span style="color:#888">-d</span> <span style="color:#777">\'{"model":"gemini-3.0-flash-thinking","messages":[{"role":"user","content":"Привет!"}]}\'</span>' +
            '</div>' +
          '</div>';
        return;
      }
      _q('histList').innerHTML = logs.map(function(r){
        var sc = r.status === 'ok' ? 'ok' : r.status === 'processing' ? 'proc' : 'err';
        var dt = r.request_at ? r.request_at.replace('T', ' ').slice(0, 16) : '—';
        var _ms = r.response_ms;
        /* D2-6: пороги response_ms подняты под реальные времена TG-моста.
           Gemini через @SamGPTrobot обычно отвечает 8–12с, поэтому:
           <8000мс = зелёный (быстро), <15000мс = жёлтый (норма),
           >=15000мс = красный (тормоз). Раньше всё, что >4с, было жёлтым. */
        var _msColor = _ms == null ? '#555' : (_ms < 8000 ? '#22c55e' : (_ms < 15000 ? '#eab308' : '#ef4444'));
        return '<div class="hist-row">' +
          '<div class="hist-status ' + sc + '"></div>' +
          '<div class="hist-info"><div class="hist-model">' + _esc(r.model || '—') + '</div><div class="hist-code">' + _esc(r.log_code || '—') + (r.error_msg ? '&nbsp;·&nbsp;<span style="color:#ef4444;font-size:10px">' + _esc(r.error_msg.slice(0, 60)) + '</span>' : '') + '</div></div>' +
          '<div class="hist-time">' + dt + '</div>' +
          '<div class="hist-ms" style="color:' + _msColor + '">' + (_ms != null ? _ms + ' мс' : '—') + '</div>' +
        '</div>';
      }).join('');
    }).catch(function(){ _q('histList').innerHTML = '<div class="hist-empty">Ошибка загрузки</div>'; });
  }

  // Экспорт на window — onclick-обработчики в HTML дёргают по имени.
  window.loadDashboard      = loadDashboard;
  window.updateTgStatus     = updateTgStatus;
  window.loadSideStats      = loadSideStats;
  window.renderKeys         = renderKeys;
  window.copyKeyVal         = copyKeyVal;
  window.regenKey           = regenKey;
  window.deleteKey          = deleteKey;
  window.createKey          = createKey;
  window.copyRawKey         = copyRawKey;
  window.closeRawKeyModal   = closeRawKeyModal;
  window.openKeySettings    = openKeySettings;
  window.onKsDualModeChange = onKsDualModeChange;
  window.saveKeySettings    = saveKeySettings;
  window.showHistory        = showHistory;
})();

export {};
