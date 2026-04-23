/* views/auth.js — авторизация (вход/регистрация/выход), синхронизация
   состояния пользователя с навигацией и сайдбаром.
   Шаг 0.5b: вынесено из inline-скрипта static/index.html.

   Все функции остаются на window, потому что HTML-обработчики (onclick=,
   onsubmit=, и inline-IIFE startup) дёргают их по имени. ESM-обёртка нужна
   только для модульной сборки через main.js — наружу ничего не экспортируем.

   Зависимости (выставлены ESM-модулями ядра ДО этого файла):
   window.api, window.q, window.openModal, window.closeModal,
   window.goView, window.updateSidebar, window.refreshNotifBadge,
   window.startNotifPolling, window.stopNotifPolling, window.rvXhr.
   Глобальные state-переменные: window.user, window.accountState. */

(function(){
  function _q(id){ return document.getElementById(id); }

  function resetAuthForm(type){
    var prefix = type === 'login' ? 'l' : 'r';
    var userInput = _q(prefix + 'User');
    var passInput = _q(prefix + 'Pass');
    var err = _q(prefix + 'Err');
    if (userInput) userInput.value = '';
    if (passInput) passInput.value = '';
    if (err) err.textContent = '';
  }

  function openEmptyRegisterModal(){
    resetAuthForm('register');
    if (window.closeModal) window.closeModal('loginModal');
    if (window.openModal) window.openModal('registerModal');
    setTimeout(function(){
      var userInput = _q('rUser');
      var passInput = _q('rPass');
      if (userInput) userInput.value = '';
      if (passInput) passInput.value = '';
      if (userInput) userInput.focus();
    }, 0);
  }

  function syncAuthState(data){
    window.accountState = data || null;
    if (data && data.user) {
      window.user = data.user;
    } else {
      window.user = null;
    }
    if (typeof window.updateNav === 'function') window.updateNav();
    if (typeof window.updateSidebar === 'function') window.updateSidebar();
    return window.user;
  }

  function handleStartFreeClick(){
    if (window.user) {
      if (window.closeModal) { window.closeModal('registerModal'); window.closeModal('loginModal'); }
      if (window.goView) window.goView('dashboard');
      return;
    }
    window.api('/api/auth/me').then(function(d){
      if (syncAuthState(d)) {
        if (window.closeModal) { window.closeModal('registerModal'); window.closeModal('loginModal'); }
        if (window.goView) window.goView('dashboard');
        return;
      }
      openEmptyRegisterModal();
    }).catch(function(){
      openEmptyRegisterModal();
    });
  }

  function doLogin(e){
    e.preventDefault();
    var btn = _q('lBtn'), err = _q('lErr');
    err.textContent = ''; btn.disabled = true; btn.textContent = 'Вход...';
    window.api('/api/auth/login', 'POST', {
      username: _q('lUser').value.trim(),
      password: _q('lPass').value,
    }).then(function(d){
      if (d.error) { err.textContent = d.message || 'Ошибка'; return; }
      window.user = d.user;
      if (window.closeModal) window.closeModal('loginModal');
      afterLogin();
    }).catch(function(){ err.textContent = 'Ошибка сети'; })
    .finally(function(){ btn.disabled = false; btn.textContent = 'Войти'; });
  }

  function doRegister(e){
    e.preventDefault();
    var btn = _q('rBtn'), err = _q('rErr');
    err.textContent = ''; btn.disabled = true; btn.textContent = 'Создание...';
    window.api('/api/auth/register', 'POST', {
      username: _q('rUser').value.trim(),
      password: _q('rPass').value,
    }).then(function(d){
      if (d.error) { err.textContent = d.message || 'Ошибка'; return; }
      window.user = d.user;
      if (window.closeModal) window.closeModal('registerModal');
      afterLogin();
    }).catch(function(){ err.textContent = 'Ошибка сети'; })
    .finally(function(){ btn.disabled = false; btn.textContent = 'Создать аккаунт'; });
  }

  function _logout(){
    // rvXhr используется намеренно (а не fetch/api) — чтобы запрос ушёл
    // даже если браузер уже закрывает страницу/таб; fetch там может оборваться.
    window.rvXhr('POST', '/api/auth/logout', null, function(){
      window.user = null;
      window.accountState = null;
      afterLogout();
    });
  }

  function afterLogin(){
    if (typeof window.updateNav === 'function') window.updateNav();
    if (typeof window.updateSidebar === 'function') window.updateSidebar();
    if (window.startNotifPolling) window.startNotifPolling();
    if (window.goView) window.goView('dashboard');
  }

  function afterLogout(){
    if (typeof window.updateNav === 'function') window.updateNav();
    if (typeof window.updateSidebar === 'function') window.updateSidebar();
    if (window.stopNotifPolling) window.stopNotifPolling();
    if (window.refreshNotifBadge) window.refreshNotifBadge();
    if (window.goView) window.goView('landing');
  }

  function updateNav(){ /* заглушка — UI уже всё рисует через updateSidebar */ }

  // Экспорт на window — onclick/onsubmit-обработчики в HTML обращаются по имени.
  window.resetAuthForm        = resetAuthForm;
  window.openEmptyRegisterModal = openEmptyRegisterModal;
  window.syncAuthState        = syncAuthState;
  window.handleStartFreeClick = handleStartFreeClick;
  window.doLogin              = doLogin;
  window.doRegister           = doRegister;
  window._logout              = _logout;
  window.afterLogin           = afterLogin;
  window.afterLogout          = afterLogout;
  window.updateNav            = updateNav;
})();

export {};
