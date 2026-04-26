/* views/setup.js — настройка Telegram-аккаунта (форма + SSE-прогресс +
   2FA + лог-консоль + импорт/экспорт session-файла).
   Шаг 0.5c: вынесено из inline-скрипта static/index.html.

   Все функции остаются на window, потому что HTML дёргает их через
   inline-обработчики (onclick=, onsubmit=, onchange=). Глобальные state
   (setupId, setupTab, sseSource, _tfaCode, _forceSetupFlowVisible,
   _setupSkipTraining) объявлены top-level в inline-скрипте и автоматически
   доступны как window.*; читаем/пишем их через window.* для устойчивости.

   _consoleLogs (буфер строк лог-консоли setup-прогресса) приватный для
   модуля — в inline он не используется ниоткуда снаружи. */

(function(){
  function _q(id){ return document.getElementById(id); }
  function _esc(s){ return window.esc ? window.esc(s) : String(s == null ? '' : s); }

  /* Локальный буфер лог-консоли. */
  var _consoleLogs = [];

  /* ───────────── PASSWORD TOGGLE / 2FA ───────────── */
  function togglePw(inputId, btn){
    var inp = _q(inputId);
    if (!inp) return;
    var show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    btn.classList.toggle('visible', show);
    btn.innerHTML = show
      ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
      : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  }

  function submitTfa(){
    var pw = _q('tfaPass').value, err = _q('tfaErr'), btn = _q('tfaBtn');
    err.textContent = '';
    if (!pw) { err.textContent = 'Введите пароль'; return; }
    if (!window._tfaCode || !window.setupId) { if (window.closeModal) window.closeModal('tfaModal'); return; }
    btn.disabled = true;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin .8s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Проверка...';
    window.api('/api/tg/setup/' + window.setupId + '/code', 'POST', { code: window._tfaCode, password: pw })
      .then(function(d){
        if (d.error) {
          err.textContent = d.message || 'Неверный пароль';
          btn.disabled = false;
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> Подтвердить';
          return;
        }
        if (window.closeModal) window.closeModal('tfaModal');
        window._tfaCode = null;
        if (d.setupId || window.setupId) trackProgress(d.setupId || window.setupId);
      })
      .catch(function(){
        err.textContent = 'Ошибка сети';
        btn.disabled = false;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> Подтвердить';
      });
  }

  /* ───────────── SESSION IMPORT / EXPORT ───────────── */
  function importSessionFile(input){
    var file = input.files[0];
    if (!file) return;
    if (window.unlockSidebarScrollIfClosed) window.unlockSidebarScrollIfClosed();
    var form = new FormData();
    form.append('file', file);
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/tg/session/import', true);
    xhr.withCredentials = true;
    xhr.timeout = 20000;
    xhr.ontimeout = function(){ window.showToast('Таймаут при загрузке файла', 'err'); if (window.unlockSidebarScrollIfClosed) window.unlockSidebarScrollIfClosed(); };
    xhr.onerror   = function(){ window.showToast('Ошибка сети при загрузке файла', 'err'); if (window.unlockSidebarScrollIfClosed) window.unlockSidebarScrollIfClosed(); };
    xhr.onload = function(){
      if (window.unlockSidebarScrollIfClosed) window.unlockSidebarScrollIfClosed();
      var d = {}; try { d = JSON.parse(xhr.responseText); } catch (e) {}
      if (d.error) { window.showToast(d.message || 'Ошибка чтения файла', 'err'); return; }
      _q('sSession').value = d.session_string || '';
      window.showToast('Файл сессии загружен', 'ok');
    };
    xhr.send(form);
    input.value = '';
    input.blur();
  }

  /* Прим.: бывшая downloadSession() удалена — она ходила в
     несуществующий /api/tg/account/session и нигде не была
     привязана к UI. Скачивание .session-файла теперь делается
     с дашборда ключей кнопкой downloadKeySession() через
     рабочий /api/keys/<id>/session. */

  /* Prog key copy — F-02. */
  function copyProgKey(btn){
    var val = _q('progKey').textContent;
    navigator.clipboard.writeText(val).then(function(){
      var orig = btn.innerHTML;
      btn.textContent = 'Скопировано!';
      setTimeout(function(){ btn.innerHTML = orig; }, 2000);
      window.showToast('Ключ скопирован', 'ok');
    });
  }

  /* ───────────── SETUP FORM ───────────── */
  function setSetupTab(tab, btn){
    window.setupTab = tab;
    document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    _q('fPhone').style.display   = tab === 'phone'   ? '' : 'none';
    _q('fSession').style.display = tab === 'session' ? '' : 'none';
    _q('sPhone').required   = tab === 'phone';
    _q('sSession').required = tab === 'session';
  }

  function startSetup(e){
    e.preventDefault();
    var err = _q('setupErr'), btn = _q('btnSetup');
    err.textContent = '';
    var apiIdVal   = _q('sApiId').value.trim();
    var apiHashVal = _q('sApiHash').value.trim();
    if (!apiIdVal || !/^\d+$/.test(apiIdVal)) {
      window.showToast('Введите корректный API ID (только цифры)', 'err');
      return;
    }
    if (!apiHashVal || !/^[a-fA-F0-9]{32}$/.test(apiHashVal)) {
      window.showToast('Введите корректный API Hash (32 символа)', 'err');
      return;
    }
    var body = { apiId: apiIdVal, apiHash: apiHashVal };
    window._setupSkipTraining = !!_q('sSkipTraining').checked;
    if (window._setupSkipTraining) body.skipTraining = true;
    if (window.setupTab === 'phone') {
      var phoneVal = _q('sPhone').value.trim();
      if (!phoneVal || !/^\+?[0-9\s\-()]{6,20}$/.test(phoneVal)) {
        window.showToast('Введите номер телефона', 'err');
        return;
      }
      body.phone = phoneVal;
    } else {
      body.sessionString = _q('sSession').value.trim();
    }
    btn.disabled = true; btn.textContent = 'Запуск...';
    window.api('/api/tg/setup', 'POST', body).then(function(d){
      if (d.error) { err.textContent = d.message || 'Ошибка'; btn.disabled = false; btn.textContent = 'Запустить настройку'; return; }
      window.setupId = d.setupId;
      // M4: новый старт — сбрасываем флаги фоновой настройки и завершения,
      // иначе после повторного «Новый ключ» guard ошибочно подумает, что
      // ничего не идёт, и закроет модалку без вопроса.
      window._setupCompleted = false;
      window._setupBackgrounded = false;
      _q('setupFormCard').style.display = 'none';
      _q('setupProgressCard').style.display = '';
      if (d.status === 'awaiting_code') _q('codeInputWrap').style.display = '';
      trackProgress(d.setupId);
    }).catch(function(){ err.textContent = 'Ошибка сети'; btn.disabled = false; btn.textContent = 'Запустить настройку'; });
  }

  /* ───────────── LOG CONSOLE ───────────── */
  function logToConsole(msg, type){
    var ts = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    _consoleLogs.push({ ts: ts, msg: msg, type: type || 'info' });
    var body = _q('logConsoleBody');
    if (!body) return;
    var line = document.createElement('div');
    line.className = 'log-line';
    var cls = type === 'error' ? 'log-err' : 'log-lbl';
    line.innerHTML = '<span class="log-ts">[' + ts + ']</span> <span class="' + cls + '">' + _esc(msg) + '</span>';
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
  }

  function toggleLogConsole(){
    var head = _q('logConsoleHead'), body = _q('logConsoleBody');
    head.classList.toggle('open');
    body.classList.toggle('open');
  }

  function copyConsoleLogs(){
    var text = _consoleLogs.map(function(l){ return '[' + l.ts + '] ' + l.msg; }).join('\n');
    navigator.clipboard.writeText(text || '(пусто)').then(function(){
      window.showToast('Логи скопированы', 'ok');
    });
  }

  /* ───────────── PROGRESS (SSE + polling) ───────────── */
  function trackProgress(sid){
    if (window.sseSource) window.sseSource.close();
    _consoleLogs = [];
    var body = _q('logConsoleBody'); if (body) body.innerHTML = '';
    logToConsole('SSE: подключение к /api/tg/setup/' + sid + '/status', 'info');
    try {
      window.sseSource = new EventSource('/api/tg/setup/' + sid + '/status');
      window.sseSource.onmessage = function(ev){
        try {
          var d = JSON.parse(ev.data);
          logToConsole('SSE << step=' + d.step + ' | ' + (d.stepLabel || '') + (d.error ? ' | ERR: ' + d.error : '') + (d.done ? ' | DONE' : ''));
          applyProgress(d);
        } catch (e) { logToConsole('SSE parse error: ' + e.message, 'error'); }
      };
      window.sseSource.onerror = function(){
        logToConsole('SSE: соединение потеряно, переход на polling', 'error');
        window.sseSource.close(); window.sseSource = null; pollProgress(sid);
      };
    } catch (e) {
      logToConsole('SSE: не удалось подключиться, polling', 'error');
      pollProgress(sid);
    }
  }

  function pollProgress(sid){
    window.api('/api/tg/setup/' + sid + '/status').then(function(d){
      logToConsole('POLL << step=' + d.step + ' | ' + (d.stepLabel || '') + (d.error ? ' | ERR: ' + d.error : '') + (d.done ? ' | DONE' : ''));
      applyProgress(d);
      // Фикс: было 3600000 ms (раз в час) — UI казался «зависшим».
      // Теперь честный live-polling раз в 3 секунды, как и должно быть
      // для фолбека с SSE.
      if (!d.done) setTimeout(function(){ pollProgress(sid); }, 3000);
    }).catch(function(){
      logToConsole('POLL: retry in 3s', 'error');
      setTimeout(function(){ pollProgress(sid); }, 3000);
    });
  }

  function applyProgress(d){
    var step = d.step || 0, total = 6;
    var skipTraining = !!window._setupSkipTraining;
    _q('progBar').style.width = Math.round(step / total * 100) + '%';
    _q('progLabel').textContent = d.stepLabel || '';
    _q('btnRetrySetup').style.display = 'none';
    _q('progErr').style.display = 'none';
    document.querySelectorAll('.prog-step').forEach(function(el){
      var s = +el.dataset.s;
      var text = el.querySelector('span');
      if (text) {
        if (!el.dataset.baseLabel) el.dataset.baseLabel = text.textContent;
        text.textContent = el.dataset.baseLabel;
      }
      el.classList.remove('s-done', 's-active');
      var icon = el.querySelector('.prog-icon');
      if (skipTraining && step > 0 && s < 6) {
        el.classList.add('s-done');
        if (s === 1) text.textContent = 'Проверка пропущена';
        if (s === 2) text.textContent = 'Запуск пропущен';
        if (s === 3) text.textContent = 'Обучение пропущено';
        if (s === 4) text.textContent = 'Настройки GPT пропущены';
        if (s === 5) text.textContent = 'Промокоды пропущены';
        icon.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:.4"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
      } else if (s < step) {
        el.classList.add('s-done');
        icon.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
      } else if (s === step) {
        el.classList.add('s-active');
        if (text && d.stepLabel) text.textContent = d.stepLabel;
      }
    });
    if (d.error) {
      var pe = _q('progErr'); pe.style.display = ''; pe.textContent = d.error;
      logToConsole('ERROR: ' + d.error, 'error');
      if (window.sseSource) { window.sseSource.close(); window.sseSource = null; }
      _q('btnRetrySetup').style.display = d.canRetry === false ? 'none' : '';
      _q('setupFormCard').style.display = 'none';
      _q('btnSetup').disabled = false; _q('btnSetup').textContent = 'Запустить настройку';
    }
    if (d.apiKey) {
      _q('progSuccess').style.display = ''; _q('progKey').textContent = d.apiKey;
      logToConsole('API KEY READY');
      _q('rawKeyDisplay').textContent = d.apiKey;
      _q('rawKeyModalTitle').textContent = 'Настройка завершена!';
      _q('rawKeyModalSub').textContent = 'Сохраните ключ — это единственный раз когда он показан полностью';
      _q('rawKeyDashBtn').style.display = '';
      if (window.openModal) window.openModal('rawKeyModal');
    }
    if (d.done && !d.error) {
      logToConsole('SETUP COMPLETE');
      if (window.sseSource) { window.sseSource.close(); window.sseSource = null; }
      window._forceSetupFlowVisible = false;
      window._setupCompleted = true;
      if (window.loadDashboard) window.loadDashboard();
    }
    if (d.status === 'awaiting_code') _q('codeInputWrap').style.display = '';
    // M4: синхронно обновляем мини-виджет (если он сейчас отрисован).
    _updateMiniWidget(d);
  }

  /* ───────────── M4: МИНИ-ВИДЖЕТ + ЗАКРЫТИЕ С ПОДТВЕРЖДЕНИЕМ ────────────
     Когда юзер жмёт ✕ на модалке настройки, мы НЕ закрываем её сразу —
     сначала спрашиваем «Прервать или продолжить в фоне?». При выборе «в
     фоне» закрываем модалку, но оставляем SSE/poll живыми, и на дашборде
     появляется мини-виджет с прогрессом. Клик по виджету заново открывает
     полноценную модалку. После завершения настройки мини сам исчезает,
     ключ автоматически подгружается через loadDashboard. */

  function _isSetupActive(){
    return !!(window.setupId && !window._setupCompleted);
  }

  function _updateMiniWidget(d){
    var card = _q('setupMiniCard');
    if (!card) return;
    // обновляем DOM мини, даже если он сейчас скрыт — чтобы при показе
    // (например при клике юзера, или при рефреше дашборда) данные были
    // уже актуальные, а не «прыгали» с дефолта.
    var step = d.step || 0, total = 6;
    var pct = Math.max(2, Math.round(step / total * 100));
    var bar = _q('setupMiniBar'); if (bar) bar.style.width = pct + '%';
    var lbl = _q('setupMiniStepLabel'); if (lbl && d.stepLabel) lbl.textContent = d.stepLabel;
    var num = _q('setupMiniStepNum'); if (num) num.textContent = step + '/' + total;
    if (card.style.display === 'none') return;
    if (d.error) {
      card.classList.remove('is-done');
      card.classList.add('is-error');
      var typE = _q('setupMiniTyp'); if (typE) typE.textContent = 'Ошибка настройки';
      if (lbl) lbl.textContent = d.error;
    } else if (d.done) {
      card.classList.remove('is-error');
      card.classList.add('is-done');
      var typD = _q('setupMiniTyp'); if (typD) typD.textContent = 'Готово!';
      if (lbl) lbl.textContent = 'Ключ создан и добавлен в дашборд';
      if (num) num.textContent = '6/6';
      // Прячем виджет с задержкой, чтобы успела проиграться зелёная
      // подсветка и юзер увидел «успех». loadDashboard уже вызван выше
      // и подтянет новый ключ.
      setTimeout(function(){
        var c = _q('setupMiniCard');
        if (c) {
          c.style.display = 'none';
          c.classList.remove('is-done', 'is-error');
        }
        window._setupBackgrounded = false;
        window.setupId = null;
      }, 2500);
    }
  }

  function showSetupMini(meta){
    var card = _q('setupMiniCard');
    if (!card) return;
    card.classList.remove('is-done', 'is-error');
    var typ = _q('setupMiniTyp'); if (typ) typ.textContent = 'Настройка';
    if (meta) {
      var u = _q('setupMiniUser');
      if (u) u.textContent = meta.user || '—';
      var a = _q('setupMiniAcct');
      if (a) a.textContent = meta.account || '—';
    }
    card.style.display = '';
  }

  function hideSetupMini(){
    var card = _q('setupMiniCard');
    if (!card) return;
    card.style.display = 'none';
    card.classList.remove('is-done', 'is-error');
  }

  /* Перехват закрытия #setupModal. Возвращает true, если модалка
     закрыта (или будет закрыта); false — если показан confirm и нужно
     прервать дефолтное закрытие. */
  function setupModalCloseGuard(){
    if (_isSetupActive()) {
      if (window.openModal) window.openModal('closeSetupConfirmModal');
      return false;
    }
    // нет активной настройки — закрываем как обычно
    window._setupModalDismissed = true;
    window._forceSetupFlowVisible = false;
    if (window.closeModal) window.closeModal('setupModal');
    return true;
  }

  /* Заменяем стандартный overlayClick для #setupModal — чтобы клик
     по фону тоже триггерил наш guard, а не закрывал модалку молча. */
  function setupOverlayClick(e, el){
    if (!e || !el || e.target !== el) return;
    setupModalCloseGuard();
  }

  /* «Прервать» в confirm-модалке */
  function setupConfirmAbort(){
    if (window.closeModal) window.closeModal('closeSetupConfirmModal');
    var sid = window.setupId;
    if (sid) {
      window.api('/api/tg/setup/' + sid + '/cancel', 'POST').catch(function(){});
    }
    if (window.sseSource) { window.sseSource.close(); window.sseSource = null; }
    window.setupId = null;
    window._setupCompleted = false;
    window._setupBackgrounded = false;
    window._forceSetupFlowVisible = false;
    hideSetupMini();
    if (window.closeModal) window.closeModal('setupModal');
    if (window.showToast) window.showToast('Настройка прервана', 'ok');
  }

  /* «Продолжить в фоне» */
  function setupConfirmBackground(){
    if (window.closeModal) window.closeModal('closeSetupConfirmModal');
    if (window.closeModal) window.closeModal('setupModal');
    window._setupBackgrounded = true;
    // Собираем мета-данные о юзере/аккаунте для виджета.
    var siteUser = (window.accountState && window.accountState.user && window.accountState.user.username) ||
                   (window.user && window.user.username) || '—';
    var apiId = (_q('sApiId') && _q('sApiId').value) ? _q('sApiId').value.trim() : '';
    var phone = (_q('sPhone') && _q('sPhone').value) ? _q('sPhone').value.trim() : '';
    var account = phone || (apiId ? ('API ID ' + apiId) : '—');
    showSetupMini({ user: siteUser, account: account });
    // Сразу подтягиваем актуальное состояние с бэка (на случай, если
    // мы зашли с пустыми полями формы — например после F5).
    if (window.api) {
      window.api('/api/tg/setup/running').then(function(r){
        if (!r || !r.running) return;
        var acct = r.tgUsername ? '@' + r.tgUsername
                  : (r.phone || (r.apiId ? 'API ID ' + r.apiId : account));
        showSetupMini({ user: siteUser, account: acct });
        var num = _q('setupMiniStepNum'); if (num) num.textContent = (r.step || 0) + '/6';
        var lbl = _q('setupMiniStepLabel'); if (lbl) lbl.textContent = r.stepLabel || 'Инициализация...';
        var bar = _q('setupMiniBar'); if (bar) bar.style.width = Math.max(2, Math.round((r.step || 0) / 6 * 100)) + '%';
      }).catch(function(){});
    }
    if (window.showToast) window.showToast('Настройка свернута — следите за прогрессом на дашборде', 'ok');
  }

  /* Клик по мини-виджету — снова открыть полноценную модалку с прогрессом. */
  function reopenSetupFromMini(){
    if (!window.setupId) {
      // нет активной настройки — просто открыть форму заново
      if (window.createKey) window.createKey();
      return;
    }
    window._forceSetupFlowVisible = true;
    if (_q('setupFormCard'))     _q('setupFormCard').style.display = 'none';
    if (_q('setupProgressCard')) _q('setupProgressCard').style.display = '';
    if (window.openModal) window.openModal('setupModal');
    // Если SSE отвалился (или мы зашли после F5) — переподключиться.
    if (!window.sseSource) {
      trackProgress(window.setupId);
    }
  }

  function cancelSetup(){
    if (!window.setupId) return;
    window.customConfirm('Отмена настройки', 'Отменить настройку Telegram?').then(function(ok){
      if (!ok) return;
      var sid = window.setupId;
      window.api('/api/tg/setup/' + sid + '/cancel', 'POST').then(function(){
        _q('setupProgressCard').style.display = 'none';
        _q('setupFormCard').style.display = '';
        _q('btnSetup').disabled = false; _q('btnSetup').textContent = 'Запустить настройку';
        // M4: сбрасываем все маркеры активной настройки, иначе guard
        // на ✕ ещё раз спросит «прервать или в фон» уже после отмены.
        if (window.sseSource) { window.sseSource.close(); window.sseSource = null; }
        window.setupId = null;
        window._setupCompleted = false;
        window._setupBackgrounded = false;
        if (typeof window.hideSetupMini === 'function') window.hideSetupMini();
      });
    });
  }

  function retrySetup(){
    if (!window.setupId) return;
    var btn = _q('btnRetrySetup'), err = _q('progErr');
    btn.disabled = true; btn.textContent = 'Повторяем...';
    err.style.display = 'none'; err.textContent = '';
    window.api('/api/tg/setup/' + window.setupId + '/retry', 'POST').then(function(d){
      btn.disabled = false; btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Повторить последний шаг';
      if (d.error) { err.style.display = ''; err.textContent = d.message || 'Ошибка повтора'; btn.style.display = ''; return; }
      btn.style.display = 'none';
      trackProgress(window.setupId);
    }).catch(function(){
      btn.disabled = false; btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Повторить последний шаг';
      err.style.display = ''; err.textContent = 'Ошибка сети при повторе'; btn.style.display = '';
    });
  }

  function submitCode(){
    var code = _q('codeInput').value.trim(), err = _q('codeErr');
    err.textContent = '';
    if (!code || !window.setupId) { err.textContent = 'Введите код'; return; }
    window.api('/api/tg/setup/' + window.setupId + '/code', 'POST', { code: code }).then(function(d){
      if (d.error) { err.textContent = d.message; return; }
      _q('codeInputWrap').style.display = 'none';
      if (d.status === 'need_password') {
        window._tfaCode = code;
        _q('tfaErr').textContent = '';
        _q('tfaPass').value = '';
        _q('tfaBtn').disabled = false;
        _q('tfaBtn').innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> Подтвердить';
        if (window.openModal) window.openModal('tfaModal');
        setTimeout(function(){ _q('tfaPass').focus(); }, 300);
      }
    });
  }

  // Экспорт на window.
  window.togglePw           = togglePw;
  window.submitTfa          = submitTfa;
  window.importSessionFile  = importSessionFile;
  window.copyProgKey        = copyProgKey;
  window.setSetupTab        = setSetupTab;
  window.startSetup         = startSetup;
  window.toggleLogConsole   = toggleLogConsole;
  window.copyConsoleLogs    = copyConsoleLogs;
  window.cancelSetup        = cancelSetup;
  window.retrySetup         = retrySetup;
  window.submitCode         = submitCode;
  // Внутренние функции, которые могут понадобиться извне (рефакторинг):
  window.trackProgress      = trackProgress;
  // M4: API мини-виджета и confirm-закрытия настройки.
  window.setupOverlayClick      = setupOverlayClick;
  window.setupModalCloseGuard   = setupModalCloseGuard;
  window.setupConfirmAbort      = setupConfirmAbort;
  window.setupConfirmBackground = setupConfirmBackground;
  window.reopenSetupFromMini    = reopenSetupFromMini;
  window.showSetupMini          = showSetupMini;
  window.hideSetupMini          = hideSetupMini;
})();

export {};
