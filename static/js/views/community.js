/* Сообщество — клиентский модуль (M3.1, рефакторинг визуала).
 * — Полноэкранный layout (см. CSS .cm-page / .cm-body / .cm-composer).
 * — Без эмодзи: SVG-иконки + Telegram-style action-sheet.
 * — Реакции — фиксированный набор (REACTIONS), на сервере хранятся как
 *   короткие коды-строки ('like', 'heart', ...). Длина <=16 байт, что
 *   укладывается в существующую валидацию в repos/community.toggle_reaction.
 * — Фон — canvas с серыми частицами, рисуется через requestAnimationFrame,
 *   stop при уходе с view (см. cmStopParticles).
 *
 * Бэкенд-эндпоинты не трогаем (они от M2/M3): /api/community/*.
 */
(function () {

  function L(tag, msg, level) {
    var prefix = '[COMMUNITY][' + tag + '] ';
    if (level === 'error') console.error(prefix + msg);
    else console.log(prefix + msg);
  }

  var STATE = {
    tab: 'chat',
    isAuth: false,
    isAdmin: false,
    chatBan: null,
    muteMentions: false,
    images: [],          // attached images (data URLs) для composer
    postImages: [],
    pollTimer: null,
    initDone: false,
    msgsCache: {},       // id → message obj (для action sheet)
    sheetMsgId: null,
    particlesAnim: null, // requestAnimationFrame id
    particlesAlive: false,
    tgState: null,
  };

  // ── Сетевой helper ─────────────────────────────────────────────────
  function http(method, url, body) {
    var opt = {
      method: method,
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
    };
    if (body) opt.body = JSON.stringify(body);
    return fetch(url, opt).then(function (r) {
      return r.text().then(function (txt) {
        var data;
        try { data = txt ? JSON.parse(txt) : {}; } catch (_e) { data = {}; }
        if (!r.ok) {
          var msg = (data && data.message) || ('HTTP ' + r.status);
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtDate(s) {
    if (!s) return '';
    return s.length > 16 ? s.slice(5, 16).replace('T', ' ') : s;
  }

  function highlightMentions(text) {
    return esc(text).replace(/@([A-Za-zА-Яа-яЁё0-9_]{2,32})/g,
      '<span class="cm-mention">@$1</span>');
  }

  // ── ICONS ──────────────────────────────────────────────────────────
  // Все SVG — outline (Lucide-стиль), 24×24 viewBox, currentColor stroke.
  var ICONS = {
    reply:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>',
    react:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
    copy:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    edit:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
    pin:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1V2H8v4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>',
    unpin:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="2" y1="2" x2="22" y2="22"/><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14"/><path d="M9 6V2h6v4"/></svg>',
    trash:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>',
    ban:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>',
    history: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><line x1="12" y1="7" x2="12" y2="12"/><line x1="12" y1="12" x2="15" y2="14"/></svg>',
    edited:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
    pinDot:  '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 9 6v5L5 16h6v6l1 0v-6h6l-4-5V6z"/></svg>',
    deleted: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>',
  };

  // Реакции — фиксированный набор. Коды короткие (<=16 байт),
  // backward-совместимы с любыми старыми эмодзи (рендерим fallback).
  var REACTIONS = [
    {code:'like',  label:'Нравится', svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7"/><path d="M2 10h5v12H2z"/></svg>'},
    {code:'heart', label:'Сердечко', svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>'},
    {code:'fire',  label:'Огонь',    svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 17c0-1.38-.5-2-1-3-.74-1.49.05-3.03 1.5-3.5.79-.26 1.14-.55 1.5-1.5.6 1 .5 1.5 0 2.5-.5 1-1.5 2-1.5 3.5 0 1 .5 2.5 2 2.5a2.5 2.5 0 0 0 2.5-2.5c0-2.21-.83-4.27-2.5-5.5C13.05 8.05 12.5 5 12.5 3c-1 .27-1.71 1.41-2 2.5C9.5 7.5 8 8.5 8 11c0 1.5.5 2 .5 3.5z"/></svg>'},
    {code:'laugh', label:'Смешно',   svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>'},
    {code:'wow',   label:'Удивление',svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="15" r="2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>'},
    {code:'sad',   label:'Грусть',   svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>'},
    {code:'clap',  label:'Аплодисменты',svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 11.5V14m0-7.5V10m0 0L7 6.5M11 10l4-3.5M5.5 10v4M18.5 10v4"/><path d="M6 14a6 6 0 0 0 12 0v-1H6v1z"/></svg>'},
    {code:'party', label:'Праздник', svg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m22 13-1.99-.59c-.62-.18-1.34.06-1.79.5L17 14.5"/><path d="m13 22 .76-2.45c.27-.83-.32-1.66-1.18-1.65L11 18"/><path d="M21 14l-7.5-7.5"/><path d="M9.27 12.73 6.5 9.97"/></svg>'},
  ];

  function reactionByCode(code) {
    for (var i=0;i<REACTIONS.length;i++) if (REACTIONS[i].code === code) return REACTIONS[i];
    return null;
  }

  function reactionRenderSvg(code) {
    var r = reactionByCode(code);
    if (r) return r.svg;
    // legacy emoji-реакции (старые сообщения) — fallback на текст.
    return '<span style="font-size:13px;line-height:1">' + esc(code) + '</span>';
  }

  // ── Переключение вкладок ────────────────────────────────────────────
  window.cmSwitchTab = function (tab) {
    L('TAB', 'switch → ' + tab);
    STATE.tab = tab;
    var t1 = document.getElementById('cmTabChat');
    var t2 = document.getElementById('cmTabPosts');
    var p1 = document.getElementById('cmChatList');
    var p2 = document.getElementById('cmPostsPane');
    var comp = document.getElementById('cmComposer');
    if (!t1 || !t2 || !p1 || !p2) return;
    if (tab === 'chat') {
      t1.classList.add('active'); t2.classList.remove('active');
      p1.style.display = ''; p2.style.display = 'none';
      if (comp) comp.style.display = '';
      loadMessages();
    } else {
      t2.classList.add('active'); t1.classList.remove('active');
      p1.style.display = 'none'; p2.style.display = '';
      if (comp) comp.style.display = 'none';
      loadPosts();
    }
  };

  // ── Состояние пользователя ──────────────────────────────────────────
  function loadState() {
    return http('GET', '/api/community/state').then(function (s) {
      STATE.isAuth = !!s.is_authenticated;
      STATE.isAdmin = !!s.is_admin;
      STATE.chatBan = s.chat_ban || null;
      STATE.muteMentions = !!s.mute_mentions;
      L('STATE', JSON.stringify({auth:STATE.isAuth, admin:STATE.isAdmin, ban:!!STATE.chatBan, mute:STATE.muteMentions}));

      var plate = document.getElementById('cmBanPlate');
      var composer = document.getElementById('cmComposer');
      if (STATE.chatBan && plate) {
        plate.style.display = '';
        plate.innerHTML = '<b>Вы забанены в чате</b> до ' + esc(STATE.chatBan.banned_until) +
          (STATE.chatBan.reason ? '. Причина: ' + esc(STATE.chatBan.reason) : '');
        if (composer) composer.style.display = 'none';
      } else if (plate) {
        plate.style.display = 'none';
        if (composer && STATE.tab === 'chat') composer.style.display = '';
      }
      if (!STATE.isAuth && composer) {
        composer.style.display = 'none';
        if (plate) {
          plate.style.display = '';
          plate.innerHTML = 'Чтобы писать в чат, войдите в аккаунт.';
        }
      }
      var pc = document.getElementById('cmAdminPostComposer');
      if (pc) pc.style.display = STATE.isAdmin ? '' : 'none';

      // Mute icon отражение
      var on = document.getElementById('cmMuteOn');
      var off = document.getElementById('cmMuteOff');
      var btn = document.getElementById('cmMuteIconBtn');
      if (on && off && btn) {
        if (STATE.muteMentions) {
          on.style.display = ''; off.style.display = 'none';
          btn.classList.add('active');
          btn.title = '@упоминания отключены — нажмите, чтобы включить';
        } else {
          on.style.display = 'none'; off.style.display = '';
          btn.classList.remove('active');
          btn.title = '@упоминания включены — нажмите, чтобы отключить';
        }
      }
    }).catch(function (e) { L('STATE_FAIL', e.message, 'error'); });
  }

  // ── Загрузка чата ───────────────────────────────────────────────────
  function loadMessages() {
    var list = document.getElementById('cmChatList');
    if (!list) return;
    return http('GET', '/api/community/messages?limit=50').then(function (data) {
      var msgs = data.messages || [];
      L('LOAD', 'msgs=' + msgs.length + ' pinned=' + (data.pinned || []).length);
      if (!msgs.length) {
        list.innerHTML = '<div style="color:#666;text-align:center;padding:30px 0">Пока нет сообщений. Будьте первым!</div>';
      } else {
        list.innerHTML = '';
        // Кешируем для action-sheet
        STATE.msgsCache = {};
        msgs.forEach(function (m) {
          STATE.msgsCache[m.id] = m;
          list.appendChild(renderMessage(m));
        });
      }
      renderPinned(data.pinned || []);
      list.scrollTop = list.scrollHeight;
    }).catch(function (e) {
      L('LOAD_FAIL', e.message, 'error');
      list.innerHTML = '<div style="color:#a44;padding:14px">Ошибка загрузки: ' + esc(e.message) + '</div>';
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
      el.className = 'cm-pinned-item';
      el.innerHTML = '<b>@' + esc(m.username) + ':</b> ' + highlightMentions(m.text || '[без текста]');
      lst.appendChild(el);
    });
  }

  // ── Рендер одного сообщения ─────────────────────────────────────────
  function renderMessage(m) {
    var el = document.createElement('div');
    el.className = 'cm-msg';
    el.dataset.id = m.id;

    if (m.is_deleted) {
      el.classList.add('cm-msg-deleted');
      el.innerHTML = '<div class="cm-msg-deleted-text">' + ICONS.deleted +
        ' Сообщение от @' + esc(m.username) + ' удалено' +
        (m.deleted_by_username ? ' (модератор: @' + esc(m.deleted_by_username) + ')' : '') +
        ' · ' + esc(fmtDate(m.deleted_at)) +
        '</div>';
      return el;
    }

    var isMine = window.__currentUserId && m.user_id === window.__currentUserId;
    if (isMine) el.classList.add('cm-msg-mine');
    if (m.pinned) el.classList.add('cm-msg-pinned');
    if (m.kind === 'admin_post') el.classList.add('cm-msg-post');

    var head = '<div class="cm-msg-head">' +
      '<span class="cm-msg-author">@' + esc(m.username) +
        (m.display_prefix ? '<span class="cm-msg-prefix">' + esc(m.display_prefix) + '</span>' : '') +
      '</span>' +
      (m.kind === 'admin_post' ? '<span class="cm-msg-badge">пост</span>' : '') +
      '<span class="cm-msg-meta-icons">' +
        (m.versions_count > 0 ? '<span title="изменено">' + ICONS.edited + '</span>' : '') +
        (m.pinned ? '<span title="закреплено">' + ICONS.pinDot + '</span>' : '') +
      '</span>' +
      '<span class="cm-msg-time">' + esc(fmtDate(m.created_at)) + '</span>' +
      '</div>';
    var body = '<div class="cm-msg-body">' + highlightMentions(m.text || '') + '</div>';
    var imgs = '';
    if (m.images && m.images.length) {
      var imgList = m.images;
      // Регистрируем массив картинок для lightbox
      var lbKey = 'cm_' + m.id;
      if (!window._lbReg) window._lbReg = {};
      window._lbReg[lbKey] = imgList;
      imgs = '<div class="cm-msg-imgs">' +
        imgList.map(function (src, idx) {
          return '<img src="' + esc(src) + '" alt="" onclick="event.stopPropagation();openLightbox(window._lbReg[\'cm_' + esc(m.id) + '\'],' + idx + ')">';
        }).join('') + '</div>';
    }
    var rx = '';
    if (m.reactions && m.reactions.length) {
      rx = '<div class="cm-msg-rx">' +
        m.reactions.map(function (r) {
          var cls = 'cm-rx-chip' + (r.mine ? ' mine' : '');
          return '<button class="' + cls + '" type="button" data-emoji="' + esc(r.emoji) + '" ' +
            'onclick="event.stopPropagation();cmReact(\'' + esc(m.id) + '\',\'' + esc(r.emoji) + '\')">' +
            reactionRenderSvg(r.emoji) +
            '<span class="cm-rx-cnt">' + r.count + '</span>' +
            '</button>';
        }).join('') + '</div>';
    }
    el.innerHTML = head + body + imgs + rx;

    // Открытие action-sheet по клику на сам пузырь (не на реакцию/картинку)
    el.addEventListener('click', function (ev) {
      // Если клик попал на ссылку @-упоминания — игнорируем (доп. ничего не делаем).
      if (ev.target.closest('.cm-rx-chip, img, a')) return;
      cmOpenSheet(m.id);
    });

    return el;
  }

  // ── Composer (отправка) ─────────────────────────────────────────────
  window.cmSendMessage = function () {
    var inp = document.getElementById('cmInput');
    if (!inp) return;
    var text = (inp.value || '').trim();
    if (!text && !STATE.images.length) return;
    L('SEND', 'len=' + text.length + ' imgs=' + STATE.images.length);
    var btn = document.getElementById('cmSendBtn');
    if (btn) btn.disabled = true;
    http('POST', '/api/community/messages', {text: text, images: STATE.images})
      .then(function () {
        inp.value = ''; STATE.images = []; renderImagesPreview();
        autosizeTextarea(inp);
        loadMessages();
      })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); })
      .finally(function () { if (btn) btn.disabled = false; });
  };

  // ── Реакция (тоггл) ─────────────────────────────────────────────────
  window.cmReact = function (msgId, code) {
    L('REACT', 'msg=' + msgId + ' code=' + code);
    http('POST', '/api/community/messages/' + msgId + '/react', {emoji: code})
      .then(function () { loadMessages(); cmCloseSheet(); })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ── Action-sheet (Telegram-like) ────────────────────────────────────
  window.cmOpenSheet = function (msgId) {
    var m = STATE.msgsCache[msgId];
    if (!m) return;
    STATE.sheetMsgId = msgId;
    var quote = document.getElementById('cmSheetQuote');
    var rxBar = document.getElementById('cmSheetRxBar');
    var actions = document.getElementById('cmSheetActions');
    var bd = document.getElementById('cmSheetBackdrop');
    var sh = document.getElementById('cmSheet');
    if (!quote || !rxBar || !actions || !bd || !sh) return;

    var snippet = (m.text || '').slice(0, 120);
    quote.innerHTML = '<b>@' + esc(m.username) + '</b>' + esc(snippet || '[медиа]');

    // Реакции (бар сверху)
    if (STATE.isAuth && !STATE.chatBan) {
      var mineMap = {};
      (m.reactions || []).forEach(function (r) { if (r.mine) mineMap[r.emoji] = true; });
      rxBar.style.display = '';
      rxBar.innerHTML = REACTIONS.map(function (r) {
        var active = mineMap[r.code] ? ' active' : '';
        return '<button class="cm-rx-bar-btn' + active + '" type="button" title="' + esc(r.label) +
          '" onclick="cmReact(\'' + esc(msgId) + '\',\'' + r.code + '\')">' + r.svg + '</button>';
      }).join('');
    } else {
      rxBar.style.display = 'none';
      rxBar.innerHTML = '';
    }

    // Действия
    var isMine = window.__currentUserId && m.user_id === window.__currentUserId;
    var rows = [];
    rows.push(actionRow(ICONS.copy, 'Скопировать текст', 'cmCopyMsg(\'' + esc(msgId) + '\')'));
    if (isMine && !m.is_deleted) {
      rows.push(actionRow(ICONS.edit, 'Редактировать', 'cmEditMsg(\'' + esc(msgId) + '\')'));
    }
    if (m.versions_count > 0) {
      rows.push(actionRow(ICONS.history, 'История правок', 'cmShowVersions(\'' + esc(msgId) + '\')'));
    }
    if (STATE.isAdmin) {
      if (m.pinned) {
        rows.push(actionRow(ICONS.unpin, 'Открепить', 'cmUnpin(\'' + esc(msgId) + '\')'));
      } else {
        rows.push(actionRow(ICONS.pin, 'Закрепить', 'cmPin(\'' + esc(msgId) + '\')'));
      }
    }
    if (isMine) {
      rows.push(actionRow(ICONS.trash, 'Удалить у себя', 'cmDeleteMsg(\'' + esc(msgId) + '\',false)', true));
    } else if (STATE.isAdmin) {
      rows.push(actionRow(ICONS.trash, 'Удалить (модерация)', 'cmDeleteMsg(\'' + esc(msgId) + '\',true)', true));
      rows.push(actionRow(ICONS.ban, 'Забанить @' + m.username, 'cmBanUser(\'' + esc(m.username) + '\')', true));
    }
    actions.innerHTML = rows.join('');

    bd.classList.add('open');
    sh.classList.add('open');
  };

  function actionRow(icon, label, onclick, danger) {
    return '<button class="cm-sheet-action' + (danger ? ' danger' : '') +
      '" type="button" onclick="cmCloseSheet();' + onclick + '">' +
      icon + '<span>' + esc(label) + '</span></button>';
  }

  window.cmCloseSheet = function () {
    var bd = document.getElementById('cmSheetBackdrop');
    var sh = document.getElementById('cmSheet');
    if (bd) bd.classList.remove('open');
    if (sh) sh.classList.remove('open');
    STATE.sheetMsgId = null;
  };

  window.cmCopyMsg = function (msgId) {
    var m = STATE.msgsCache[msgId];
    if (!m) return;
    var t = m.text || '';
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(t).then(function () {
        if (window.showToast) window.showToast('Скопировано', 'ok');
      }).catch(function () { fallbackCopy(t); });
    } else { fallbackCopy(t); }
  };
  function fallbackCopy(t) {
    var ta = document.createElement('textarea');
    ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); if (window.showToast) window.showToast('Скопировано', 'ok'); }
    catch (_e) {}
    document.body.removeChild(ta);
  }

  window.cmEditMsg = function (msgId) {
    var m = STATE.msgsCache[msgId];
    if (!m) return;
    var v = prompt('Редактировать сообщение:', m.text || '');
    if (v == null) return;
    http('PATCH', '/api/community/messages/' + msgId, {text: v})
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmDeleteMsg = function (msgId, asAdmin) {
    if (!confirm(asAdmin ? 'Удалить сообщение модерацией?' : 'Удалить своё сообщение?')) return;
    var url = asAdmin ? '/api/community/admin/messages/' + msgId
                      : '/api/community/messages/' + msgId;
    http('DELETE', url)
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmPin = function (msgId) {
    http('POST', '/api/community/messages/' + msgId + '/pin')
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmUnpin = function (msgId) {
    http('DELETE', '/api/community/messages/' + msgId + '/pin')
      .then(loadMessages)
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmBanUser = function (username) {
    var hours = prompt('Забанить @' + username + ' (часы):', '24');
    if (!hours) return;
    var reason = prompt('Причина (можно пусто):', '') || '';
    http('POST', '/api/community/admin/bans', {username: username, hours: parseInt(hours, 10), reason: reason})
      .then(function () { if (window.showToast) window.showToast('Бан выдан', 'ok'); })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmShowVersions = function (msgId) {
    http('GET', '/api/community/messages/' + msgId + '/versions').then(function (d) {
      var lines = (d.versions || []).map(function (v) {
        return '— ' + fmtDate(v.created_at) + '\n' + (v.text || '[пусто]');
      }).join('\n\n');
      alert('История правок:\n\n' + (lines || 'нет версий'));
    }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ── Composer images / mute ──────────────────────────────────────────
  var CM_MAX_IMAGES = 10;

  window.cmHandleFiles = function (ev) {
    var files = ev.target.files;
    if (!files) return;
    var remaining = CM_MAX_IMAGES - STATE.images.length;
    var arr = Array.prototype.slice.call(files, 0, remaining);
    if (STATE.images.length >= CM_MAX_IMAGES) {
      if (window.showToast) window.showToast('Максимум ' + CM_MAX_IMAGES + ' фото', 'err');
      ev.target.value = '';
      return;
    }
    arr.forEach(function (f) {
      if (STATE.images.length >= CM_MAX_IMAGES) return;
      var rd = new FileReader();
      rd.onload = function () {
        STATE.images.push(rd.result);
        renderImagesPreview();
      };
      rd.readAsDataURL(f);
    });
    ev.target.value = '';
  };

  window.cmRemoveImg = function (i) { STATE.images.splice(i, 1); renderImagesPreview(); };

  function renderImagesPreview() {
    var box = document.getElementById('cmImagesPreview');
    if (!box) return;
    if (!STATE.images.length) {
      box.style.display = 'none'; box.innerHTML = ''; return;
    }
    box.style.display = 'flex';
    var snapshots = STATE.images.slice(); // snapshot for closure
    box.innerHTML = snapshots.map(function (src, i) {
      return '<div class="cm-composer-img-item">' +
        '<img src="' + esc(src) + '" alt="" onclick="openLightbox(window._cmComposerImgs,' + i + ')">' +
        '<button class="cm-composer-rmimg" onclick="cmRemoveImg(' + i + ')" type="button">×</button>' +
        '</div>';
    }).join('') +
    (STATE.images.length >= CM_MAX_IMAGES
      ? '<div class="cm-composer-img-limit">макс. ' + CM_MAX_IMAGES + '</div>' : '');
    window._cmComposerImgs = snapshots;
  }

  window.cmHandlePostFiles = function (ev) {
    var files = ev.target.files;
    if (!files) return;
    var remaining = CM_MAX_IMAGES - STATE.postImages.length;
    var arr = Array.prototype.slice.call(files, 0, remaining);
    if (STATE.postImages.length >= CM_MAX_IMAGES) {
      if (window.showToast) window.showToast('Максимум ' + CM_MAX_IMAGES + ' фото', 'err');
      ev.target.value = '';
      return;
    }
    arr.forEach(function (f) {
      if (STATE.postImages.length >= CM_MAX_IMAGES) return;
      var rd = new FileReader();
      rd.onload = function () {
        STATE.postImages.push(rd.result);
        renderPostImagesPreview();
      };
      rd.readAsDataURL(f);
    });
    ev.target.value = '';
  };
  window.cmRemovePostImg = function (i) { STATE.postImages.splice(i, 1); renderPostImagesPreview(); };
  function renderPostImagesPreview() {
    var box = document.getElementById('cmPostImagesPreview');
    if (!box) return;
    if (!STATE.postImages.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    box.style.display = '';
    box.innerHTML = STATE.postImages.map(function (src, i) {
      return '<div class="cm-composer-img-item"><img src="' + esc(src) + '" style="max-width:90px;max-height:90px;border-radius:6px;border:1px solid #1f1f1f" alt=""><button class="cm-composer-rmimg" onclick="cmRemovePostImg(' + i + ')" type="button">×</button></div>';
    }).join('') +
    (STATE.postImages.length >= CM_MAX_IMAGES
      ? '<div class="cm-composer-img-limit">макс. ' + CM_MAX_IMAGES + '</div>' : '');
  }

  window.cmToggleMute = function () {
    var newVal = !STATE.muteMentions;
    L('MUTE', 'set=' + newVal);
    http('POST', '/api/community/mute_mentions', {mute: newVal})
      .then(function (r) {
        STATE.muteMentions = !!r.mute;
        loadState();
      })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ── Создание поста (только админ) ───────────────────────────────────
  window.cmCreatePost = function () {
    var inp = document.getElementById('cmPostInput');
    if (!inp) return;
    var text = (inp.value || '').trim();
    if (!text && !STATE.postImages.length) return;
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

  function loadPosts() {
    var list = document.getElementById('cmPostsList');
    if (!list) return;
    return http('GET', '/api/community/posts?limit=30').then(function (data) {
      var posts = data.posts || [];
      if (!posts.length) {
        list.innerHTML = '<div style="color:#666;text-align:center;padding:30px 0">Постов пока нет.</div>';
        return;
      }
      list.innerHTML = '';
      posts.forEach(function (m) {
        STATE.msgsCache[m.id] = m;
        list.appendChild(renderMessage(m));
      });
    }).catch(function (e) {
      list.innerHTML = '<div style="color:#a44;padding:14px">Ошибка: ' + esc(e.message) + '</div>';
    });
  }

  // ── TG-уведомления (модал) ──────────────────────────────────────────
  function loadTgState() {
    return http('GET', '/api/community/tg_link').then(function (s) {
      STATE.tgState = s;
      renderTgChip(s);
      renderTgModal(s);
    }).catch(function (e) { L('TG_FAIL', e.message, 'error'); });
  }

  function renderTgChip(s) {
    var btn = document.getElementById('cmTgIconBtn');
    var line = document.getElementById('cmTgLine');
    var lineText = document.getElementById('cmTgLineText');
    var lineStatus = document.getElementById('cmTgLineStatus');
    if (!s || !s.available) {
      if (btn) btn.style.display = 'none';
      if (line) line.classList.remove('shown');
      return;
    }
    if (btn) {
      btn.style.display = '';
      btn.classList.toggle('active', !!s.linked);
      btn.title = s.linked ? 'Telegram-уведомления привязаны — нажмите для настроек'
                            : 'Подключить Telegram для уведомлений';
    }
    if (line) {
      // Подсказка-чип над списком — показываем только если НЕ привязан, чтобы не маячила.
      if (s.linked) {
        line.classList.remove('shown');
      } else {
        line.classList.add('shown');
        if (lineText) lineText.textContent = 'Подключить Telegram, чтобы получать пуши о @упоминаниях';
        if (lineStatus) lineStatus.textContent = 'настроить →';
      }
    }
  }

  function renderTgModal(s) {
    var body = document.getElementById('cmTgModalBody');
    if (!body) return;
    if (!s) { body.innerHTML = '<div style="color:#a44">Не удалось загрузить статус.</div>'; return; }
    if (!s.available) {
      body.innerHTML = '<div style="color:#888">Бот уведомлений не настроен на сервере. Уведомления о @упоминаниях приходят только в раздел колокола.</div>';
      return;
    }
    if (s.linked) {
      var when = s.linked_at ? (' · ' + esc(s.linked_at)) : '';
      body.innerHTML =
        '<div style="color:#9fdf9f;margin-bottom:10px">Telegram привязан (chat_id: <code>' + esc(s.chat_id) + '</code>' + when + ').</div>' +
        '<div style="color:#aaa;margin-bottom:14px">Когда вас упомянут <span class="cm-mention">@ник</span> в общем чате — пуш придёт сюда. Внутреннее уведомление в колоколе создаётся всегда.</div>' +
        '<button class="cm-iconbtn" style="width:auto;padding:0 14px;height:36px;color:#ff8a8a" onclick="cmTgUnlink()" type="button">Отвязать</button>';
    } else {
      var url = s.link_url ? esc(s.link_url) : '';
      body.innerHTML =
        '<div style="color:#aaa;margin-bottom:10px">Подключите бота <b>@' + esc(s.bot_username || '?') +
          '</b>, чтобы получать пуши о @упоминаниях.</div>' +
        (url
          ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">' +
              '<a href="' + url + '" target="_blank" rel="noopener" class="cm-iconbtn" style="width:auto;padding:0 14px;height:36px;background:#15263e;color:#cfe2ff;border-color:#2c5b9c;text-decoration:none">Открыть в Telegram</a>' +
              '<button class="cm-iconbtn" style="width:auto;padding:0 12px;height:36px" onclick="cmTgRegen()" type="button" title="Старая ссылка перестанет работать">Сгенерировать заново</button>' +
            '</div>' +
            '<div style="color:#666;font-size:11.5px;margin-bottom:14px">Ссылка одноразовая. После /start у бота сюда придёт подтверждение.</div>'
          : '') +
        '<details><summary style="cursor:pointer;color:#888;font-size:12.5px">Привязать вручную по chat_id</summary>' +
          '<div style="margin-top:10px;color:#aaa">Узнайте свой chat_id в <code>@userinfobot</code>. Перед этим обязательно напишите <b>/start</b> нашему боту, иначе он не сможет писать вам в личку.</div>' +
          '<div style="display:flex;gap:6px;margin-top:10px">' +
            '<input type="text" id="cmTgManual" placeholder="например: 123456789" inputmode="numeric">' +
            '<button class="cm-iconbtn" style="width:auto;padding:0 12px;height:36px" onclick="cmTgManual()" type="button">Привязать</button>' +
          '</div>' +
        '</details>';
    }
  }

  window.cmOpenTgModal = function () {
    document.getElementById('cmTgBackdrop').classList.add('open');
    document.getElementById('cmTgModal').classList.add('open');
    if (!STATE.tgState) loadTgState();
  };
  window.cmCloseTgModal = function () {
    document.getElementById('cmTgBackdrop').classList.remove('open');
    document.getElementById('cmTgModal').classList.remove('open');
  };
  window.cmTgRegen = function () {
    http('POST', '/api/community/tg_link/regenerate').then(function (s) {
      STATE.tgState = s; renderTgChip(s); renderTgModal(s);
    }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };
  window.cmTgManual = function () {
    var inp = document.getElementById('cmTgManual');
    if (!inp) return;
    var v = (inp.value || '').trim();
    if (!v) return;
    http('POST', '/api/community/tg_link/manual', {chat_id: v}).then(function (s) {
      STATE.tgState = s; renderTgChip(s); renderTgModal(s);
      if (window.showToast) window.showToast('Telegram привязан', 'ok');
    }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };
  window.cmTgUnlink = function () {
    if (!confirm('Отвязать Telegram?')) return;
    http('DELETE', '/api/community/tg_link').then(function (s) {
      STATE.tgState = s; renderTgChip(s); renderTgModal(s);
    }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ── Auto-resize textarea ────────────────────────────────────────────
  function autosizeTextarea(t) {
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = Math.min(120, t.scrollHeight) + 'px';
  }

  // ── Particles canvas (фон) ──────────────────────────────────────────
  function startParticles() {
    var cv = document.getElementById('cmParticles');
    if (!cv || STATE.particlesAlive) return;
    var ctx = cv.getContext('2d');
    var dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    var W = 0, H = 0;
    var particles = [];

    function resize() {
      var r = cv.getBoundingClientRect();
      W = Math.max(1, r.width|0); H = Math.max(1, r.height|0);
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Целевая плотность ~ 1 частица на 16k пикс. Минимум 30, максимум 110.
      var target = Math.min(110, Math.max(30, Math.round(W * H / 16000)));
      while (particles.length < target) particles.push(makeParticle());
      while (particles.length > target) particles.pop();
    }
    function makeParticle() {
      return {
        x: Math.random() * (W || 320),
        y: Math.random() * (H || 320),
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        r: 0.6 + Math.random() * 1.2,
        a: 0.12 + Math.random() * 0.18,
      };
    }
    resize();
    var ro = (typeof ResizeObserver !== 'undefined') ? new ResizeObserver(resize) : null;
    if (ro) ro.observe(cv); else window.addEventListener('resize', resize);

    function tick() {
      if (!STATE.particlesAlive) return;
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < -2) p.x = W + 2; else if (p.x > W + 2) p.x = -2;
        if (p.y < -2) p.y = H + 2; else if (p.y > H + 2) p.y = -2;
        ctx.beginPath();
        ctx.fillStyle = 'rgba(180,180,180,' + p.a.toFixed(3) + ')';
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      STATE.particlesAnim = requestAnimationFrame(tick);
    }
    STATE.particlesAlive = true;
    STATE.particlesAnim = requestAnimationFrame(tick);
    L('PARTICLES', 'started');
  }
  function stopParticles() {
    if (STATE.particlesAnim) cancelAnimationFrame(STATE.particlesAnim);
    STATE.particlesAlive = false;
    STATE.particlesAnim = null;
  }
  window.cmStopParticles = stopParticles;

  // ── Инициализация ──────────────────────────────────────────────────
  window.initCommunityView = function () {
    L('INIT', 'enter');
    var inp = document.getElementById('cmInput');
    if (inp) {
      inp.addEventListener('input', function () { autosizeTextarea(inp); });
      inp.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
          ev.preventDefault();
          window.cmSendMessage();
        }
      });
      autosizeTextarea(inp);
    }

    startParticles();
    loadState().then(function () {
      if (STATE.tab === 'chat') loadMessages();
      else loadPosts();
      if (STATE.isAuth) loadTgState();
    });

    if (STATE.pollTimer) clearInterval(STATE.pollTimer);
    STATE.pollTimer = setInterval(function () {
      var view = document.getElementById('view-community');
      if (view && view.classList.contains('active')) {
        if (STATE.tab === 'chat') loadMessages();
      } else {
        clearInterval(STATE.pollTimer); STATE.pollTimer = null;
        stopParticles();
      }
    }, 8000);
    STATE.initDone = true;
  };

  // Если юзер уйдёт по Esc / нажмёт back-button браузера —
  // гасим частицы и закрываем sheet.
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') {
      var sh = document.getElementById('cmSheet');
      if (sh && sh.classList.contains('open')) cmCloseSheet();
      var tg = document.getElementById('cmTgModal');
      if (tg && tg.classList.contains('open')) cmCloseTgModal();
    }
  });

  L('MOD', 'community.js loaded (M3.1 refactor)');
})();
