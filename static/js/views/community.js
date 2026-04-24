/* views/community.js — раздел «Сообщество» (общий чат + посты админов).
 *
 * Подробное логирование (clog) — потому что отлаживать SQLite-чат через
 * WebView в Termux без логов невозможно. Каждое действие/HTTP — отдельная
 * запись в /docs/logcodes.
 */
(function () {
  'use strict';

  function L(tag, msg, level) {
    try { if (window.clog) window.clog('CM_' + tag, msg, level || 'info'); } catch (_) {}
    try { console.log('[CM][' + tag + ']', msg); } catch (_) {}
  }

  var STATE = {
    tab: 'chat',          // 'chat' | 'posts'
    isAdmin: false,
    isAuth: false,
    chatBan: null,
    muteMentions: false,
    composerImages: [],   // base64 data-urls
    postImages: [],
    pollTimer: null,
    lastSeenId: null,
    initDone: false,
  };

  // ─── ХЕЛПЕРЫ HTTP ──────────────────────────────────────────────────
  function http(method, url, body) {
    L('HTTP', method + ' ' + url + (body ? (' body=' + JSON.stringify(body).slice(0,200)) : ''));
    return fetch(url, {
      method: method,
      credentials: 'include',
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = {raw: txt}; }
        if (!r.ok) {
          L('HTTP_ERR', method + ' ' + url + ' → ' + r.status + ' msg=' + (data && data.message || ''), 'error');
          var err = new Error((data && data.message) || ('HTTP ' + r.status));
          err.status = r.status; err.data = data;
          throw err;
        }
        L('HTTP_OK', method + ' ' + url + ' → ' + r.status);
        return data;
      });
    });
  }

  // ─── ESC ──────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function fmtDate(s) {
    if (!s) return '';
    // sqlite stores 'YYYY-MM-DD HH:MM:SS' в МСК
    return s.replace(/^\d{4}-(\d{2})-(\d{2}) (\d{2}:\d{2}):\d{2}$/, '$2.$1 $3');
  }

  function highlightMentions(text) {
    // безопасный escape сначала, потом выделяем @user
    var safe = esc(text || '');
    return safe.replace(/(^|\s)@([A-Za-z0-9_]{2,32})/g,
      '$1<span style="color:#7eb6ff;font-weight:500">@$2</span>');
  }

  // ─── ПЕРЕКЛЮЧЕНИЕ ВКЛАДОК ─────────────────────────────────────────
  window.cmSwitchTab = function (tab) {
    L('TAB', 'switch → ' + tab);
    STATE.tab = tab;
    var t1 = document.getElementById('cmTabChat');
    var t2 = document.getElementById('cmTabPosts');
    var p1 = document.getElementById('cmChatPane');
    var p2 = document.getElementById('cmPostsPane');
    if (!t1 || !t2 || !p1 || !p2) return;
    if (tab === 'chat') {
      t1.style.background = '#1a1a1a'; t2.style.background = '';
      p1.style.display = ''; p2.style.display = 'none';
      loadMessages();
    } else {
      t1.style.background = ''; t2.style.background = '#1a1a1a';
      p1.style.display = 'none'; p2.style.display = '';
      loadPosts();
    }
  };

  // ─── СОСТОЯНИЕ ─────────────────────────────────────────────────────
  function loadState() {
    return http('GET', '/api/community/state').then(function (s) {
      STATE.isAuth = !!s.is_authenticated;
      STATE.isAdmin = !!s.is_admin;
      STATE.chatBan = s.chat_ban || null;
      STATE.muteMentions = !!s.mute_mentions;
      L('STATE', JSON.stringify({auth: STATE.isAuth, admin: STATE.isAdmin, ban: !!STATE.chatBan, mute: STATE.muteMentions}));

      // Плашка бана
      var plate = document.getElementById('cmBanPlate');
      var composer = document.getElementById('cmComposer');
      if (STATE.chatBan && plate) {
        plate.style.display = '';
        plate.innerHTML = '<b>Вы забанены в чате</b> до ' + esc(STATE.chatBan.banned_until) +
          (STATE.chatBan.reason ? '. Причина: ' + esc(STATE.chatBan.reason) : '');
        if (composer) composer.style.display = 'none';
      } else if (plate) {
        plate.style.display = 'none';
        if (composer) composer.style.display = '';
      }
      // Если не авторизован — спрятать composer
      if (!STATE.isAuth && composer) {
        composer.style.display = 'none';
        if (plate) {
          plate.style.display = '';
          plate.innerHTML = 'Чтобы писать в чат, войдите в аккаунт.';
        }
      }
      // Композер постов — только админу
      var pc = document.getElementById('cmAdminPostComposer');
      if (pc) pc.style.display = STATE.isAdmin ? '' : 'none';
      // Mute checkbox
      var mu = document.getElementById('cmMuteMentions');
      if (mu) mu.checked = STATE.muteMentions;
    }).catch(function (e) {
      L('STATE_FAIL', e.message, 'error');
    });
  }

  // ─── ЗАГРУЗКА ЧАТА ────────────────────────────────────────────────
  function loadMessages() {
    var list = document.getElementById('cmChatList');
    if (!list) return;
    return http('GET', '/api/community/messages?limit=50').then(function (data) {
      var msgs = (data.messages || []).slice().reverse(); // показываем хронологически снизу→вверх не делаем; держим DESC сверху
      // Лучше: oldest сверху, newest снизу — переворачиваем массив, пришедший DESC.
      list.innerHTML = '';
      if (!msgs.length) {
        list.innerHTML = '<div style="color:#666;text-align:center;padding:30px 0">Пока нет сообщений. Будьте первым!</div>';
      } else {
        msgs.forEach(function (m) { list.appendChild(renderMessage(m)); });
        list.scrollTop = list.scrollHeight;
      }
      // Закреп
      renderPinned(data.pinned || []);
      L('LIST', 'messages=' + msgs.length + ' pinned=' + ((data.pinned || []).length));
    }).catch(function (e) {
      list.innerHTML = '<div style="color:#c66;text-align:center;padding:30px 0">Не удалось загрузить чат: ' + esc(e.message) + '</div>';
    });
  }

  function renderPinned(pins) {
    var box = document.getElementById('cmPinned');
    var lst = document.getElementById('cmPinnedList');
    if (!box || !lst) return;
    if (!pins.length) { box.style.display = 'none'; return; }
    box.style.display = '';
    lst.innerHTML = '';
    pins.forEach(function (m) {
      var el = document.createElement('div');
      el.style.cssText = 'padding:6px 0;border-top:1px dashed #1f1f1f;font-size:12.5px;color:#bbb';
      el.innerHTML = '<b style="color:#eee">@' + esc(m.username) + ':</b> ' + highlightMentions(m.text || '[без текста]');
      lst.appendChild(el);
    });
  }

  function renderMessage(m) {
    var el = document.createElement('div');
    el.style.cssText = 'padding:8px 0;border-bottom:1px solid #161616';
    el.dataset.id = m.id;
    if (m.is_deleted) {
      el.innerHTML = '<div style="color:#777;font-style:italic;font-size:12px">' +
        '🚫 Сообщение от @' + esc(m.username) + ' удалено' +
        (m.deleted_by_username ? ' (модератор: @' + esc(m.deleted_by_username) + ')' : '') +
        ' • ' + esc(fmtDate(m.deleted_at)) +
        '</div>';
      return el;
    }
    var isMine = window.__currentUserId && m.user_id === window.__currentUserId;
    var head = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">' +
      '<b style="color:#eee">@' + esc(m.username) + '</b>' +
      (m.kind === 'admin_post' ? '<span style="font-size:10px;background:#2a2a4a;color:#a8b8ff;padding:1px 6px;border-radius:4px">ПОСТ</span>' : '') +
      '<span style="font-size:10px;color:#666">' + esc(fmtDate(m.created_at)) + '</span>' +
      (m.versions_count > 0 ? '<span style="font-size:10px;color:#888" title="Изменено">✎</span>' : '') +
      (m.pinned ? '<span style="font-size:10px;color:#888">📌</span>' : '') +
      '</div>';
    var body = '<div style="white-space:pre-wrap;word-break:break-word">' + highlightMentions(m.text || '') + '</div>';
    var imgs = '';
    if (m.images && m.images.length) {
      imgs = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">' +
        m.images.map(function (src) {
          return '<img src="' + esc(src) + '" style="max-width:120px;max-height:120px;border-radius:6px;border:1px solid #1f1f1f;cursor:pointer" onclick="window.open(this.src)">';
        }).join('') + '</div>';
    }
    var rx = '';
    if (m.reactions && m.reactions.length) {
      rx = '<div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap">' +
        m.reactions.map(function (r) {
          return '<button class="cm-rx" data-mid="' + esc(m.id) + '" data-emoji="' + esc(r.emoji) + '" ' +
            'style="background:' + (r.mine ? '#1c2a3a' : '#161616') + ';border:1px solid ' + (r.mine ? '#2c5a8a' : '#222') +
            ';border-radius:12px;padding:2px 8px;font-size:11px;color:#ddd;cursor:pointer" ' +
            'onclick="cmReact(\'' + esc(m.id) + '\',\'' + esc(r.emoji) + '\')">' +
            esc(r.emoji) + ' ' + r.count + '</button>';
        }).join('') + '</div>';
    }
    var actions = '<div style="display:flex;gap:6px;margin-top:6px;font-size:11px;color:#666">';
    actions += '<a href="#" onclick="cmReactPrompt(\'' + esc(m.id) + '\');return false" style="color:#888">+реакция</a>';
    if (isMine || STATE.isAdmin) {
      if (isMine) actions += '<a href="#" onclick="cmEditMsg(\'' + esc(m.id) + '\');return false" style="color:#888">✎ ред.</a>';
      actions += '<a href="#" onclick="cmDeleteMsg(\'' + esc(m.id) + '\',' + (isMine ? 'false' : 'true') + ');return false" style="color:#c88">✕ удалить</a>';
    }
    if (STATE.isAdmin) {
      actions += '<a href="#" onclick="' + (m.pinned ? 'cmUnpin' : 'cmPin') + '(\'' + esc(m.id) + '\');return false" style="color:#888">' + (m.pinned ? 'открепить' : 'закрепить') + '</a>';
      if (!isMine) actions += '<a href="#" onclick="cmBanUser(\'' + esc(m.username) + '\');return false" style="color:#c88">бан</a>';
    }
    actions += '</div>';
    el.innerHTML = head + body + imgs + rx + actions;
    return el;
  }

  // ─── ОТПРАВКА ──────────────────────────────────────────────────────
  window.cmSendMessage = function () {
    var inp = document.getElementById('cmInput');
    if (!inp) return;
    var text = (inp.value || '').trim();
    if (!text && !STATE.composerImages.length) return;
    L('SEND', 'len=' + text.length + ' imgs=' + STATE.composerImages.length);
    var btn = document.getElementById('cmSendBtn');
    if (btn) btn.disabled = true;
    http('POST', '/api/community/messages', {text: text, images: STATE.composerImages})
      .then(function () {
        inp.value = '';
        STATE.composerImages = [];
        renderImagesPreview();
        loadMessages();
      })
      .catch(function (e) {
        if (window.showToast) window.showToast('Не отправлено: ' + e.message, 'err');
      })
      .finally(function () { if (btn) btn.disabled = false; });
  };

  window.cmEditMsg = function (id) {
    var newText = prompt('Новый текст сообщения:');
    if (newText == null) return;
    L('EDIT', 'msg=' + id);
    http('PATCH', '/api/community/messages/' + encodeURIComponent(id), {text: newText, images: []})
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmDeleteMsg = function (id, asAdmin) {
    if (!confirm(asAdmin ? 'Удалить сообщение как модератор?' : 'Удалить ваше сообщение?')) return;
    L('DEL', 'msg=' + id + ' admin=' + asAdmin);
    var url = '/api/community/messages/' + encodeURIComponent(id) + (asAdmin ? '/admin' : '');
    http('DELETE', url).then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmReactPrompt = function (id) {
    var emoji = prompt('Введите emoji для реакции (👍 ❤ 🔥 …):', '👍');
    if (!emoji) return;
    cmReact(id, emoji);
  };
  window.cmReact = function (id, emoji) {
    L('REACT', 'msg=' + id + ' emoji=' + emoji);
    http('POST', '/api/community/messages/' + encodeURIComponent(id) + '/react', {emoji: emoji})
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmPin = function (id) {
    L('PIN', 'msg=' + id);
    http('POST', '/api/community/messages/' + encodeURIComponent(id) + '/pin')
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };
  window.cmUnpin = function (id) {
    L('UNPIN', 'msg=' + id);
    http('DELETE', '/api/community/messages/' + encodeURIComponent(id) + '/pin')
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmBanUser = function (username) {
    var days = prompt('Бан пользователя @' + username + ' на сколько дней?', '7');
    if (!days) return;
    var reason = prompt('Причина (опц.):', '') || '';
    L('BAN_REQ', 'user=' + username + ' days=' + days);
    http('POST', '/api/community/bans', {username: username, days: parseInt(days, 10), reason: reason})
      .then(function () { if (window.showToast) window.showToast('Забанен', 'ok'); loadMessages(); })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ─── КАРТИНКИ ──────────────────────────────────────────────────────
  function readFileAsDataURL(file) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () { resolve(fr.result); };
      fr.onerror = reject;
      fr.readAsDataURL(file);
    });
  }

  window.cmHandleFiles = function (ev) {
    var files = Array.from(ev.target.files || []);
    L('FILES', 'count=' + files.length);
    Promise.all(files.slice(0, 4).map(readFileAsDataURL)).then(function (urls) {
      // Проверяем размер ≤200KB
      var ok = urls.filter(function (u) { return u.length <= 220000; });
      if (ok.length !== urls.length) {
        if (window.showToast) window.showToast('Некоторые фото >200KB были отброшены', 'warn');
      }
      STATE.composerImages = STATE.composerImages.concat(ok).slice(0, 4);
      renderImagesPreview();
      ev.target.value = '';
    });
  };

  function renderImagesPreview() {
    var box = document.getElementById('cmImagesPreview');
    if (!box) return;
    if (!STATE.composerImages.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    box.style.display = 'flex';
    box.innerHTML = STATE.composerImages.map(function (u, i) {
      return '<div style="position:relative">' +
        '<img src="' + esc(u) + '" style="width:60px;height:60px;object-fit:cover;border-radius:6px;border:1px solid #222">' +
        '<button onclick="cmRemoveImg(' + i + ')" style="position:absolute;top:-6px;right:-6px;background:#400;border:1px solid #800;color:#fff;border-radius:50%;width:18px;height:18px;cursor:pointer;font-size:11px;line-height:1">✕</button>' +
        '</div>';
    }).join('');
  }
  window.cmRemoveImg = function (i) {
    STATE.composerImages.splice(i, 1); renderImagesPreview();
  };

  window.cmHandlePostFiles = function (ev) {
    var files = Array.from(ev.target.files || []);
    Promise.all(files.slice(0, 4).map(readFileAsDataURL)).then(function (urls) {
      STATE.postImages = STATE.postImages.concat(urls.filter(function (u) { return u.length <= 220000; })).slice(0, 4);
      renderPostImagesPreview();
      ev.target.value = '';
    });
  };

  function renderPostImagesPreview() {
    var box = document.getElementById('cmPostImagesPreview');
    if (!box) return;
    if (!STATE.postImages.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    box.style.display = 'flex';
    box.innerHTML = STATE.postImages.map(function (u, i) {
      return '<div style="position:relative">' +
        '<img src="' + esc(u) + '" style="width:60px;height:60px;object-fit:cover;border-radius:6px;border:1px solid #222">' +
        '<button onclick="cmRemovePostImg(' + i + ')" style="position:absolute;top:-6px;right:-6px;background:#400;border:1px solid #800;color:#fff;border-radius:50%;width:18px;height:18px;cursor:pointer;font-size:11px;line-height:1">✕</button>' +
        '</div>';
    }).join('');
  }
  window.cmRemovePostImg = function (i) { STATE.postImages.splice(i, 1); renderPostImagesPreview(); };

  // ─── MUTE @ ───────────────────────────────────────────────────────
  window.cmToggleMute = function (ev) {
    var v = !!(ev.target && ev.target.checked);
    L('MUTE', 'value=' + v);
    http('POST', '/api/community/mute_mentions', {mute: v})
      .then(function () { STATE.muteMentions = v; })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ─── ПОСТЫ ────────────────────────────────────────────────────────
  function loadPosts() {
    var box = document.getElementById('cmPostsList');
    if (!box) return;
    return http('GET', '/api/community/posts?limit=30').then(function (d) {
      var posts = d.posts || [];
      box.innerHTML = '';
      if (!posts.length) {
        box.innerHTML = '<div style="color:#666;text-align:center;padding:30px 0">Пока нет постов.</div>';
      } else {
        posts.forEach(function (p) {
          var el = document.createElement('div');
          el.style.cssText = 'background:#0a0a0a;border:1px solid #1c1c1c;border-radius:12px;padding:12px';
          el.appendChild(renderMessage(p));
          box.appendChild(el);
        });
      }
      L('POSTS', 'count=' + posts.length);
    }).catch(function (e) {
      box.innerHTML = '<div style="color:#c66;text-align:center;padding:30px 0">Ошибка загрузки: ' + esc(e.message) + '</div>';
    });
  }

  window.cmCreatePost = function () {
    var inp = document.getElementById('cmPostInput');
    if (!inp) return;
    var text = (inp.value || '').trim();
    if (!text && !STATE.postImages.length) return;
    L('POST_NEW', 'len=' + text.length);
    var btn = document.getElementById('cmPostBtn');
    if (btn) btn.disabled = true;
    http('POST', '/api/community/posts', {text: text, images: STATE.postImages})
      .then(function () {
        inp.value = ''; STATE.postImages = []; renderPostImagesPreview();
        loadPosts();
      })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); })
      .finally(function () { if (btn) btn.disabled = false; });
  };

  // ─── ИНИЦИАЛИЗАЦИЯ ────────────────────────────────────────────────
  window.initCommunityView = function () {
    L('INIT', 'enter');
    loadState().then(function () {
      if (STATE.tab === 'chat') loadMessages();
      else loadPosts();
    });
    if (STATE.pollTimer) clearInterval(STATE.pollTimer);
    STATE.pollTimer = setInterval(function () {
      var view = document.getElementById('view-community');
      if (view && view.classList.contains('active')) {
        if (STATE.tab === 'chat') loadMessages();
      } else {
        clearInterval(STATE.pollTimer); STATE.pollTimer = null;
      }
    }, 8000);
    STATE.initDone = true;
  };

  L('MOD', 'community.js loaded');
})();
