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
    replyTo: null,       // M3.5: {id, username, snippet} — Telegram-style reply
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

  // M3.6: «online / был N минут назад» по unix-таймштампу last_seen_at.
  // < 60 сек → online; до часа → минуты; до суток → часы; до месяца → дни;
  // дальше — пусто (показывать «был полгода назад» бессмысленно).
  function fmtLastSeen(unixSec) {
    if (!unixSec) return '';
    var ago = Math.floor(Date.now() / 1000) - Number(unixSec);
    if (ago < 0) ago = 0;
    if (ago < 60) return 'online';
    if (ago < 3600) {
      var m = Math.floor(ago / 60);
      return 'был ' + m + ' мин назад';
    }
    if (ago < 86400) {
      var h = Math.floor(ago / 3600);
      return 'был ' + h + ' ч назад';
    }
    if (ago < 86400 * 30) {
      var d = Math.floor(ago / 86400);
      return 'был ' + d + ' д назад';
    }
    return '';
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

  // Emoji Picker — нативные эмодзи для реакций (исключение из SVG-правила).
  // Backward-compat: старые SVG-коды ('like','heart',...) рендерятся через fallback.
  var EMOJI_PICKER_LIST = [
    '👍','❤️','😂','🔥','🎉','😮','😢','😡',
    '👏','💯','🤔','💪','🙏','😎','✅','🥳',
    '😭','🤣','🫶','💀','🫡','🤝','⭐','🤩',
    '😊','😁','👀','🤯','💔','🥺','😍','🫠',
  ];

  // ── M3.4/M3.5: кастомные избранные эмодзи (хранятся в localStorage) ────
  var CM_CUSTOM_EMOJI_KEY = 'cm_custom_emojis_v1';
  var CM_CUSTOM_EMOJI_MAX = 32;

  function cmGetCustomEmojis() {
    try {
      var raw = localStorage.getItem(CM_CUSTOM_EMOJI_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.filter(function (x) { return typeof x === 'string' && x; }) : [];
    } catch (_e) { return []; }
  }
  function cmSaveCustomEmojis(arr) {
    try { localStorage.setItem(CM_CUSTOM_EMOJI_KEY, JSON.stringify(arr.slice(0, CM_CUSTOM_EMOJI_MAX))); }
    catch (_e) {}
  }

  // M3.5: ровно 1 emoji-grapheme. Telegram использует Intl.Segmenter
  // (granularity:'grapheme'), который правильно считает составные
  // emoji с ZWJ, vs-16, тоном кожи и флагами как 1 единицу.
  // Fallback на Array.from если Segmenter недоступен.
  function cmCountGraphemes(s) {
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      try {
        var seg = new Intl.Segmenter('en', { granularity: 'grapheme' });
        var n = 0;
        var it = seg.segment(s)[Symbol.iterator]();
        while (!it.next().done) n++;
        return n;
      } catch (_e) { /* fallthrough */ }
    }
    return Array.from(s).length;
  }

  window.cmAddCustomEmoji = function (msgId) {
    cmPrompt('Введите ровно 1 эмодзи (например 🦊). Можно сохранить до ' + CM_CUSTOM_EMOJI_MAX + ' штук.', '', function (v) {
      var s = (v || '').trim();
      if (!s) return;
      if (s.length > 16) {
        if (window.showToast) window.showToast('Слишком длинно (макс. 16 символов)', 'err');
        return;
      }
      // M3.5: разрешаем РОВНО один графемный кластер. Без этого юзер
      // вводил несколько эмодзи подряд («❤️❤️💜💙💜💜») и они шли
      // на бэк как одна реакция, а сетка пикера разъезжалась.
      var n = cmCountGraphemes(s);
      if (n !== 1) {
        if (window.showToast) window.showToast('Нужен ровно 1 эмодзи (введено: ' + n + ')', 'err');
        return;
      }
      var list = cmGetCustomEmojis();
      if (list.length >= CM_CUSTOM_EMOJI_MAX) {
        if (window.showToast) window.showToast('Достигнут лимит ' + CM_CUSTOM_EMOJI_MAX + ' эмодзи', 'err');
        return;
      }
      // Не дублируем — ни кастомные, ни базовые.
      if (list.indexOf(s) !== -1 || EMOJI_PICKER_LIST.indexOf(s) !== -1) {
        if (window.showToast) window.showToast('Уже в избранном', 'err');
      } else {
        list.push(s);
        cmSaveCustomEmojis(list);
        if (window.showToast) window.showToast('Добавлено: ' + s, 'ok');
      }
      // Перерисовать пикер, если он открыт для этого сообщения.
      if (STATE.sheetMsgId) {
        var m = STATE.msgsCache[STATE.sheetMsgId];
        var rxBar = document.getElementById('cmSheetRxBar');
        if (m && rxBar) {
          var mineSet = {};
          (m.reactions || []).forEach(function (r) { if (r.mine) mineSet[r.emoji] = true; });
          rxBar.innerHTML = renderEmojiPicker(STATE.sheetMsgId, mineSet);
        }
      }
    });
  };
  window.cmRemoveCustomEmoji = function (emoji, ev) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    var list = cmGetCustomEmojis();
    var idx = list.indexOf(emoji);
    if (idx === -1) return;
    list.splice(idx, 1);
    cmSaveCustomEmojis(list);
    if (window.showToast) window.showToast('Убрано из избранных', 'ok');
    if (STATE.sheetMsgId) {
      var m = STATE.msgsCache[STATE.sheetMsgId];
      var rxBar = document.getElementById('cmSheetRxBar');
      if (m && rxBar) {
        var mineSet = {};
        (m.reactions || []).forEach(function (r) { if (r.mine) mineSet[r.emoji] = true; });
        rxBar.innerHTML = renderEmojiPicker(STATE.sheetMsgId, mineSet);
      }
    }
  };

  // SVG-плюс для кнопки «добавить свой эмодзи»
  var ICON_PLUS_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';

  function renderEmojiPicker(msgId, mineSet) {
    mineSet = mineSet || {};
    var custom = cmGetCustomEmojis();
    var stdHtml = EMOJI_PICKER_LIST.map(function (e) {
      var active = mineSet[e] ? ' active' : '';
      return '<button class="cm-emoji-btn' + active + '" type="button" ' +
        'onclick="cmReact(\'' + esc(msgId) + '\',\'' + esc(e) + '\')">' + e + '</button>';
    }).join('');
    var customHtml = custom.map(function (e) {
      var active = mineSet[e] ? ' active' : '';
      return '<span class="cm-emoji-btn-wrap">' +
        '<button class="cm-emoji-btn cm-emoji-btn-custom' + active + '" type="button" ' +
          'onclick="cmReact(\'' + esc(msgId) + '\',\'' + esc(e) + '\')">' + esc(e) + '</button>' +
        '<button class="cm-emoji-btn-rm" type="button" title="Убрать из избранных" ' +
          'onclick="cmRemoveCustomEmoji(\'' + esc(e) + '\',event)">×</button>' +
        '</span>';
    }).join('');
    var addBtn = '<button class="cm-emoji-btn cm-emoji-btn-add" type="button" title="Добавить свой эмодзи в избранное" ' +
      'onclick="cmAddCustomEmoji(\'' + esc(msgId) + '\')">' + ICON_PLUS_SVG + '</button>';
    return '<div class="cm-emoji-picker">' + stdHtml + customHtml + addBtn + '</div>';
  }

  // Обратная совместимость: старые coded-реакции → SVG
  var _LEGACY_REACTIONS = {
    like:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7"/><path d="M2 10h5v12H2z"/></svg>',
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
    fire:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 17c0-1.38-.5-2-1-3-.74-1.49.05-3.03 1.5-3.5.79-.26 1.14-.55 1.5-1.5.6 1 .5 1.5 0 2.5-.5 1-1.5 2-1.5 3.5 0 1 .5 2.5 2 2.5a2.5 2.5 0 0 0 2.5-2.5c0-2.21-.83-4.27-2.5-5.5C13.05 8.05 12.5 5 12.5 3c-1 .27-1.71 1.41-2 2.5C9.5 7.5 8 8.5 8 11c0 1.5.5 2 .5 3.5z"/></svg>',
    laugh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
    wow:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="15" r="2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
    sad:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
    clap:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 11.5V14m0-7.5V10m0 0L7 6.5M11 10l4-3.5M5.5 10v4M18.5 10v4"/><path d="M6 14a6 6 0 0 0 12 0v-1H6v1z"/></svg>',
    party: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m22 13-1.99-.59c-.62-.18-1.34.06-1.79.5L17 14.5"/><path d="m13 22 .76-2.45c.27-.83-.32-1.66-1.18-1.65L11 18"/><path d="M21 14l-7.5-7.5"/><path d="M9.27 12.73 6.5 9.97"/></svg>',
  };

  function reactionRenderSvg(code) {
    if (_LEGACY_REACTIONS[code]) return _LEGACY_REACTIONS[code];
    // нативный эмодзи или неизвестный код — показываем текстом
    return '<span style="font-size:17px;line-height:1">' + esc(code) + '</span>';
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
    // M3.5.2: chip «↓ новые» относится только к чату — снимаем при любом
    // переключении вкладок, чтобы не висел над лентой постов.
    cmHideNewMsgChip();
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

      // Синхронизируем toggle в разделе «Уведомления» если он открыт
      window.cmSyncNotifMuteToggle && window.cmSyncNotifMuteToggle();
    }).catch(function (e) { L('STATE_FAIL', e.message, 'error'); });
  }

  // ── Загрузка чата ───────────────────────────────────────────────────
  // M3.5.2: бэк отдаёт сообщения DESC (новые первые) ради пагинации
  // (`before_id` = older). Чтобы UI был Telegram-style (старые сверху, новые
  // снизу), на фронте делаем .slice().reverse(). Также после рендера сразу
  // скроллим в самый низ.
  function loadMessages() {
    var list = document.getElementById('cmChatList');
    if (!list) return;
    return http('GET', '/api/community/messages?limit=50').then(function (data) {
      var msgs = (data.messages || []).slice().reverse();
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
      cmHideNewMsgChip();
      // requestAnimationFrame: дожидаемся layout перед скроллом — иначе
      // scrollHeight ещё не финальный (особенно с фото, которые подгружаются).
      requestAnimationFrame(function () { list.scrollTop = list.scrollHeight; });
    }).catch(function (e) {
      L('LOAD_FAIL', e.message, 'error');
      list.innerHTML = '<div style="color:#a44;padding:14px">Ошибка загрузки: ' + esc(e.message) + '</div>';
    });
  }

  // M3.5.2: инкрементальный poll-обновлятор. Вместо полного refresh:
  //   - тянем последние 50 (DESC),
  //   - находим только реально НОВЫЕ id (которых нет в кеше),
  //   - синхронизируем УЖЕ существующие в кеше (для подъезжающих реакций
  //     других юзеров — обновляем элемент на месте, скролл не сбивается),
  //   - новые добавляем СНИЗУ. Если юзер у низа (within 80px) — авто-скролл,
  //     иначе показываем chip «↓ N новых сообщений».
  function loadMessagesPoll() {
    var list = document.getElementById('cmChatList');
    if (!list) return loadMessages();
    return http('GET', '/api/community/messages?limit=50').then(function (data) {
      var fresh = (data.messages || []).slice().reverse();
      if (!fresh.length) { renderPinned(data.pinned || []); return; }

      // Если кеш пустой (после переключения вкладок и т.п.) — fallback на full load.
      if (!Object.keys(STATE.msgsCache).length) {
        list.innerHTML = '';
        fresh.forEach(function (m) {
          STATE.msgsCache[m.id] = m;
          list.appendChild(renderMessage(m));
        });
        renderPinned(data.pinned || []);
        cmHideNewMsgChip();
        requestAnimationFrame(function () { list.scrollTop = list.scrollHeight; });
        return;
      }

      var newOnes = [];
      fresh.forEach(function (m) {
        if (STATE.msgsCache[m.id]) {
          // Существующее: обновляем кеш и DOM. cmRerenderMessage делает
          // replaceChild — scrollTop не сбивается.
          STATE.msgsCache[m.id] = m;
          cmRerenderMessage(m.id);
        } else {
          newOnes.push(m);
        }
      });

      renderPinned(data.pinned || []);
      if (!newOnes.length) return;

      var atBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) < 80;
      newOnes.forEach(function (m) {
        STATE.msgsCache[m.id] = m;
        list.appendChild(renderMessage(m));
      });

      if (atBottom) {
        cmHideNewMsgChip();
        requestAnimationFrame(function () { list.scrollTop = list.scrollHeight; });
      } else {
        cmShowNewMsgChip(newOnes.length);
      }
    }).catch(function (e) {
      L('POLL_FAIL', e.message, 'error');
    });
  }

  // M3.5.2: chip «↓ Новые сообщения». Подсчёт идёт суммарно с момента
  // последнего показа — пока юзер не нажмёт chip и не скроллит вниз сам.
  function cmShowNewMsgChip(addCount) {
    var chip = document.getElementById('cmNewMsgChip');
    var txt = document.getElementById('cmNewMsgChipText');
    if (!chip || !txt) return;
    STATE.newMsgChipCount = (STATE.newMsgChipCount || 0) + addCount;
    var n = STATE.newMsgChipCount;
    txt.textContent = n === 1 ? '1 новое сообщение' :
      ((n < 5) ? n + ' новых сообщения' : n + ' новых сообщений');
    chip.classList.add('shown');
  }
  function cmHideNewMsgChip() {
    var chip = document.getElementById('cmNewMsgChip');
    if (chip) chip.classList.remove('shown');
    STATE.newMsgChipCount = 0;
  }
  // Вызывается из onclick chip'а и при переключении вкладок.
  window.cmJumpToBottom = function () {
    var list = document.getElementById('cmChatList');
    if (!list) return;
    cmHideNewMsgChip();
    list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' });
  };
  // Если юзер сам доскроллил вниз — снимаем chip автоматически.
  function _bindChatScrollListener() {
    var list = document.getElementById('cmChatList');
    if (!list || list._cmScrollBound) return;
    list._cmScrollBound = true;
    list.addEventListener('scroll', function () {
      if (!STATE.newMsgChipCount) return;
      var atBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) < 60;
      if (atBottom) cmHideNewMsgChip();
    }, { passive: true });
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
  // M3.6 / T10: круглая аватарка слева. Поддерживает image / gif / video
  // через avatar_media (новое поле). Старое avatar (data URL) всё ещё
  // понимается как kind='image'.
  function renderMsgAvatar(m) {
    var media = m.avatar_media || (m.avatar ? { kind: 'image', url: m.avatar } : null);
    if (media && media.kind === 'video') {
      var cs = isFinite(media.clip_start) ? Number(media.clip_start) : 0;
      var ce = isFinite(media.clip_end) ? Number(media.clip_end) : (cs + 10);
      var fragUrl = esc(media.url) + '#t=' + cs.toFixed(2) + ',' + ce.toFixed(2);
      return '<div class="cm-msg-avatar">' +
        '<video class="cm-msg-avatar-video" src="' + fragUrl + '" ' +
        'autoplay muted playsinline preload="auto" ' +
        'data-clip-start="' + cs.toFixed(2) + '" ' +
        'data-clip-end="' + ce.toFixed(2) + '" disablepictureinpicture></video>' +
        '</div>';
    }
    if (media) {
      return '<div class="cm-msg-avatar">' +
        '<img class="cm-msg-avatar-img" src="' + esc(media.url) + '" alt="">' +
        '</div>';
    }
    var ch = String(m.username || '?').trim().charAt(0).toUpperCase() || '?';
    return '<div class="cm-msg-avatar cm-msg-avatar-letter">' + esc(ch) + '</div>';
  }

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

    // M3.4/M3.5: если у юзера нет своего display_prefix, но он админ —
    // показываем дефолтный бейдж «Владелец» (раньше было «Admin»),
    // чтобы ReZero и др. админы были видны без ручной настройки.
    var prefixText = m.display_prefix || (m.is_admin ? 'Владелец' : null);
    // M3.5.1: префикс вынесен из <span.cm-msg-author> наружу, чтобы он был
    // полноправным flex-соседом badge'а «пост». Иначе из-за align по baseline
    // разнокалиберные шрифты (13/10/9.5px) визуально выстраивались лесенкой.
    // Класс cm-msg-prefix-owner теперь ставится для ВСЕХ админов (раньше — только
    // если у юзера не было кастомного префикса), чтобы переливался как .badge-owner.
    // M3.6: статус «онлайн / был N мин назад» рядом с ником.
    // Считаем дельту по часам клиента — допускаем небольшой дрейф.
    var onlineHtml = '';
    if (m.last_seen_at) {
      var lbl = fmtLastSeen(m.last_seen_at);
      if (lbl) {
        var isOnline = lbl === 'online';
        onlineHtml = '<span class="cm-msg-online" data-online="' +
          (isOnline ? '1' : '0') + '">' + esc(lbl) + '</span>';
      }
    }
    var head = '<div class="cm-msg-head">' +
      '<span class="cm-msg-author">@' + esc(m.username) + '</span>' +
      (prefixText ? '<span class="cm-msg-prefix' + (m.is_admin ? ' cm-msg-prefix-owner' : '') + '">' + esc(prefixText) + '</span>' : '') +
      (m.kind === 'admin_post' ? '<span class="cm-msg-badge">пост</span>' : '') +
      onlineHtml +
      '<span class="cm-msg-meta-icons">' +
        (m.versions_count > 0 ? '<span title="изменено">' + ICONS.edited + '</span>' : '') +
        (m.pinned ? '<span title="закреплено">' + ICONS.pinDot + '</span>' : '') +
      '</span>' +
      '<span class="cm-msg-time">' + esc(fmtDate(m.created_at)) + '</span>' +
      '</div>';
    // M3.5: Telegram-style цитата ответа над телом сообщения. Клик
    // по цитате скроллит к оригиналу (если он ещё в DOM).
    var replyHtml = '';
    if (m.reply_to) {
      var rt = m.reply_to;
      replyHtml = '<div class="cm-msg-reply" data-reply-id="' + esc(rt.id) + '" ' +
        'onclick="event.stopPropagation();cmScrollToMsg(\'' + esc(rt.id) + '\')">' +
        '<div class="cm-msg-reply-bar"></div>' +
        '<div class="cm-msg-reply-body">' +
          '<div class="cm-msg-reply-author">@' + esc(rt.username) + '</div>' +
          '<div class="cm-msg-reply-text">' + esc(rt.text_snippet) + '</div>' +
        '</div></div>';
    }
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
    // M3.6: новая структура — flex-row: [аватар] [контент]
    el.innerHTML = renderMsgAvatar(m) +
      '<div class="cm-msg-content">' + head + replyHtml + body + imgs + rx + '</div>';

    // Открытие action-sheet по клику на сам пузырь (не на реакцию/картинку/цитату/аватарку)
    el.addEventListener('click', function (ev) {
      // Если клик попал на ссылку @-упоминания / реакцию / картинку / цитату / аватарку — игнорируем.
      if (ev.target.closest('.cm-rx-chip, img, a, .cm-msg-reply, .cm-msg-avatar')) return;
      cmOpenSheet(m.id);
    });

    return el;
  }

  // M3.5/M3.6: скролл к оригиналу при клике на цитату ответа.
  // Ищем сообщение в DOM обеих лент (чат + посты). Если нашли в неактивной
  // вкладке — переключаемся туда и скроллим. Если вообще не нашли — пробуем
  // подтянуть из API (узнать kind), переключиться на нужную вкладку и
  // догрузить ленту, потом скроллим.
  function _cmFindMsgInDom(msgId) {
    var sel = '.cm-msg[data-id="' + String(msgId).replace(/"/g, '\\"') + '"]';
    var inChat = document.querySelector('#cmChatList ' + sel);
    var inPosts = document.querySelector('#cmPostsList ' + sel);
    if (inChat) return { el: inChat, tab: 'chat' };
    if (inPosts) return { el: inPosts, tab: 'posts' };
    return null;
  }

  function _cmFlashAndScroll(el) {
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('cm-msg-flash');
    setTimeout(function () { el.classList.remove('cm-msg-flash'); }, 1400);
  }

  function _cmTryScroll(msgId) {
    var hit = _cmFindMsgInDom(msgId);
    if (!hit) return false;
    if (hit.tab !== STATE.tab) {
      cmSwitchTab(hit.tab);
      // даём ленте перерисоваться после загрузки
      setTimeout(function () {
        var hit2 = _cmFindMsgInDom(msgId);
        if (hit2) _cmFlashAndScroll(hit2.el);
      }, 80);
    } else {
      _cmFlashAndScroll(hit.el);
    }
    return true;
  }

  window.cmScrollToMsg = function (msgId) {
    if (!msgId) return;
    if (_cmTryScroll(msgId)) return;
    // Сообщения нет в DOM ни одной из лент — спрашиваем сервер про его kind,
    // переключаем вкладку, ждём догрузки и пробуем ещё раз.
    http('GET', '/api/community/message/' + encodeURIComponent(msgId))
      .then(function (resp) {
        var msg = resp && resp.message;
        if (!msg) {
          if (window.showToast) window.showToast('Сообщение не найдено', 'err');
          return;
        }
        var targetTab = (msg.kind === 'admin_post') ? 'posts' : 'chat';
        if (targetTab !== STATE.tab) cmSwitchTab(targetTab);
        // Ждём, пока loadMessages/loadPosts отрисует свежий список.
        var attempts = 0;
        var iv = setInterval(function () {
          attempts++;
          if (_cmTryScroll(msgId)) { clearInterval(iv); return; }
          if (attempts >= 20) {
            clearInterval(iv);
            if (window.showToast) window.showToast('Сообщение не найдено', 'err');
          }
        }, 150);
      })
      .catch(function () {
        if (window.showToast) window.showToast('Сообщение не найдено', 'err');
      });
  };

  // ── Composer (отправка) ─────────────────────────────────────────────
  window.cmSendMessage = function () {
    var inp = document.getElementById('cmInput');
    if (!inp) return;
    var text = (inp.value || '').trim();
    if (!text && !STATE.images.length) return;
    var replyTo = STATE.replyTo;  // M3.5
    L('SEND', 'len=' + text.length + ' imgs=' + STATE.images.length + ' reply=' + (replyTo ? replyTo.id : '-'));
    var btn = document.getElementById('cmSendBtn');
    if (btn) btn.disabled = true;
    var payload = {text: text, images: STATE.images};
    if (replyTo && replyTo.id) payload.reply_to_id = replyTo.id;
    // M3.5.2: после успеха используем инкрементальный poll вместо полного
    // refresh — это добавит наше новое сообщение СНИЗУ (через cmShowNewMsgChip
    // оно не пройдёт, потому что юзер только что был у низа → atBottom=true →
    // авто-скролл).
    http('POST', '/api/community/messages', payload)
      .then(function () {
        inp.value = ''; STATE.images = []; renderImagesPreview();
        STATE.replyTo = null; cmRenderReplyBar();  // M3.5
        autosizeTextarea(inp);
        // Принудительно прокрутим к низу ДО poll'а — чтобы atBottom-гейт
        // в loadMessagesPoll сработал и наше сообщение проехало без chip'а.
        var list = document.getElementById('cmChatList');
        if (list) list.scrollTop = list.scrollHeight;
        loadMessagesPoll();
      })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); })
      .finally(function () { if (btn) btn.disabled = false; });
  };

  // ── Реакция (Telegram-style: один эмодзи на юзера) ──────────────────
  // M3.5: оптимистичное обновление — сразу мутируем кеш и перерисовываем
  // конкретное сообщение, без ожидания ответа сервера. Если сервер ругнётся,
  // откатываемся и перерисовываем повторно.
  window.cmReact = function (msgId, code) {
    L('REACT', 'msg=' + msgId + ' code=' + code);
    var m = STATE.msgsCache[msgId];
    if (!m) {
      // Кеш потерян (например после reload) — fallback на старый сценарий.
      http('POST', '/api/community/messages/' + msgId + '/react', {emoji: code})
        .then(function () { loadMessages(); cmCloseSheet(); })
        .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
      return;
    }
    // Snapshot для отката.
    var snapshot = JSON.parse(JSON.stringify(m.reactions || []));
    // Оптимистичная single-reaction логика (зеркалит бэк):
    var rxs = (m.reactions || []).map(function (r) { return Object.assign({}, r); });
    var myOld = null;
    rxs.forEach(function (r) { if (r.mine) myOld = r.emoji; });
    // Снимаем мою старую реакцию (любую).
    rxs = rxs.map(function (r) {
      if (r.mine) { r = Object.assign({}, r, {mine: false, count: r.count - 1}); }
      return r;
    }).filter(function (r) { return r.count > 0; });
    if (myOld !== code) {
      // Ставлю новую (если такой уже есть в массиве — увеличиваю counter).
      var found = false;
      rxs = rxs.map(function (r) {
        if (r.emoji === code) { found = true; return Object.assign({}, r, {mine: true, count: r.count + 1}); }
        return r;
      });
      if (!found) rxs.push({emoji: code, count: 1, mine: true});
    }
    m.reactions = rxs;
    cmRerenderMessage(msgId);
    cmCloseSheet();

    http('POST', '/api/community/messages/' + msgId + '/react', {emoji: code})
      .then(function (resp) {
        // Сервер вернул свежий объект — обновим кеш и перерисуем (синхронизация).
        if (resp && resp.message) {
          STATE.msgsCache[msgId] = resp.message;
          cmRerenderMessage(msgId);
        }
      })
      .catch(function (e) {
        // Откат
        m.reactions = snapshot;
        cmRerenderMessage(msgId);
        if (window.showToast) window.showToast(e.message, 'err');
      });
  };

  // M3.5: пересоздать DOM-элемент одного сообщения (без перезагрузки чата).
  // M3.5.1: ищем глобально (а не только в #cmChatList), чтобы фикс работал
  // и для постов в #cmPostsList — иначе оптимистичная реакция на пост
  // мутировала кеш, но DOM оставался старым (визуально реакция не появлялась).
  function cmRerenderMessage(msgId) {
    var safe = String(msgId).replace(/(["\\])/g, '\\$1');
    var old = document.querySelector('.cm-msg[data-id="' + safe + '"]');
    var m = STATE.msgsCache[msgId];
    if (!old || !m) return;
    var fresh = renderMessage(m);
    old.parentNode.replaceChild(fresh, old);
  }

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

    // Emoji Picker (вместо фиксированных SVG-реакций) + M3.4: кастомные избранные эмодзи
    if (STATE.isAuth && !STATE.chatBan) {
      var mineSet = {};
      (m.reactions || []).forEach(function (r) { if (r.mine) mineSet[r.emoji] = true; });
      rxBar.style.display = '';
      rxBar.innerHTML = renderEmojiPicker(msgId, mineSet);
    } else {
      rxBar.style.display = 'none';
      rxBar.innerHTML = '';
    }

    // Действия
    var isMine = window.__currentUserId && m.user_id === window.__currentUserId;
    var rows = [];
    rows.push(actionRow(ICONS.copy, 'Скопировать текст', 'cmCopyMsg(\'' + esc(msgId) + '\')'));
    // M3.5: «Ответить» доступно ВСЕМ, у кого есть право писать в чат
    // (как в Telegram). Прячем только для удалённых сообщений и для
    // забаненных/неавторизованных.
    if (STATE.isAuth && !STATE.chatBan && !m.is_deleted) {
      rows.push(actionRow(ICONS.reply, 'Ответить', 'cmReply(\'' + esc(msgId) + '\')'));
    }
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
    cmPrompt('Редактировать сообщение:', m.text || '', function (v) {
      if (v == null) return;
      http('PATCH', '/api/community/messages/' + msgId, {text: v})
        .then(loadMessages)
        .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
    });
  };

  // M3.5: оптимистичное удаление — DOM убираем сразу, при ошибке загружаем заново.
  window.cmDeleteMsg = function (msgId, asAdmin) {
    var msg = asAdmin ? 'Удалить сообщение модерацией?' : 'Удалить своё сообщение?';
    cmConfirm(msg, function () {
      var list = document.getElementById('cmChatList');
      var el = list ? list.querySelector('.cm-msg[data-id="' + msgId + '"]') : null;
      var prev = el ? el.outerHTML : null;
      var nextSibling = el ? el.nextSibling : null;
      var parent = el ? el.parentNode : null;
      if (el) el.remove();
      // M3.4: правильный путь — /messages/<id>/admin (ранее фронт слал /admin/messages/<id> → 405)
      var url = asAdmin ? '/api/community/messages/' + msgId + '/admin'
                        : '/api/community/messages/' + msgId;
      http('DELETE', url)
        .then(function () {
          // Сервер всё равно вернёт «удалённый огрызок» при следующем poll,
          // но мы уже скрыли DOM — хорошее ощущение Telegram-like.
          delete STATE.msgsCache[msgId];
        })
        .catch(function (e) {
          if (parent && prev) {
            // Откат: вставляем элемент обратно туда же.
            var tmp = document.createElement('div');
            tmp.innerHTML = prev;
            parent.insertBefore(tmp.firstChild, nextSibling);
          }
          if (window.showToast) window.showToast(e.message, 'err');
        });
    });
  };

  // M3.5: оптимистичный pin/unpin — мутируем m.pinned, перерисовываем msg
  // и блок закреплённых; при ошибке откатываемся.
  window.cmPin = function (msgId) {
    var m = STATE.msgsCache[msgId];
    var prev = m ? m.pinned : null;
    if (m) { m.pinned = true; cmRerenderMessage(msgId); }
    http('POST', '/api/community/messages/' + msgId + '/pin')
      .then(loadMessages)
      .catch(function (e) {
        if (m) { m.pinned = prev; cmRerenderMessage(msgId); }
        if (window.showToast) window.showToast(e.message, 'err');
      });
  };

  window.cmUnpin = function (msgId) {
    var m = STATE.msgsCache[msgId];
    var prev = m ? m.pinned : null;
    if (m) { m.pinned = false; cmRerenderMessage(msgId); }
    http('DELETE', '/api/community/messages/' + msgId + '/pin')
      .then(loadMessages)
      .catch(function (e) {
        if (m) { m.pinned = prev; cmRerenderMessage(msgId); }
        if (window.showToast) window.showToast(e.message, 'err');
      });
  };

  // ── M3.5: Reply (Telegram-style) ────────────────────────────────────
  window.cmReply = function (msgId) {
    var m = STATE.msgsCache[msgId];
    if (!m) return;
    var snippet = (m.text || '').slice(0, 120) || '[медиа]';
    STATE.replyTo = {id: msgId, username: m.username, snippet: snippet};
    cmRenderReplyBar();
    var inp = document.getElementById('cmInput');
    if (inp) { try { inp.focus(); } catch (_e) {} }
  };
  window.cmCancelReply = function () {
    STATE.replyTo = null;
    cmRenderReplyBar();
  };
  function cmRenderReplyBar() {
    var bar = document.getElementById('cmComposerReply');
    if (!bar) return;
    if (!STATE.replyTo) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
    var rt = STATE.replyTo;
    bar.style.display = '';
    bar.innerHTML =
      '<div class="cm-composer-reply-bar"></div>' +
      '<div class="cm-composer-reply-body">' +
        '<div class="cm-composer-reply-author">Ответ @' + esc(rt.username) + '</div>' +
        '<div class="cm-composer-reply-text">' + esc(rt.snippet) + '</div>' +
      '</div>' +
      '<button class="cm-composer-reply-x" type="button" onclick="cmCancelReply()" title="Отменить ответ">×</button>';
  }

  window.cmBanUser = function (username) {
    // M3.4: бэкенд ждёт POST /api/community/bans с {days, reason}
    cmPrompt('Забанить @' + username + ' на сколько дней? (1..365)', '7', function (days) {
      if (!days) return;
      var d = parseInt(days, 10) || 7;
      if (d < 1) d = 1; else if (d > 365) d = 365;
      cmPrompt('Причина (оставьте пустым для пропуска):', '', function (reason) {
        http('POST', '/api/community/bans', {username: username, days: d, reason: reason || ''})
          .then(function () { if (window.showToast) window.showToast('Бан выдан на ' + d + ' дн.', 'ok'); })
          .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
      });
    });
  };

  window.cmShowVersions = function (msgId) {
    http('GET', '/api/community/messages/' + msgId + '/versions').then(function (d) {
      var lines = (d.versions || []).map(function (v) {
        return fmtDate(v.created_at) + ':\n' + (v.text || '[пусто]');
      }).join('\n\n');
      cmAlert('История правок', lines || 'Нет версий.');
    }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  // ── Composer images / mute ──────────────────────────────────────────
  var CM_MAX_IMAGES = 10;

  // M3.4: читаем файлы через Promise.all, чтобы все картинки гарантированно
  // попали в STATE.images ДО того, как юзер успеет кликнуть «отправить».
  // Раньше использовался forEach с асинхронным FileReader → race condition,
  // и при 2 фото на сервер уходило только 1 (см. логи 25.04: images=1).
  //
  // M3.5: каждое фото ужимаем через <canvas>: max сторона 1280, JPEG q=0.85.
  // Современные смартфонные снимки 2-4MB ужимаются до 100-300 KB и комфортно
  // влезают в новый бэкенд-лимит 2.5 MB. Если на каком-то этапе сжатие
  // упало — возвращаем оригинал (а бэк уже умеет принимать до 2.5 MB).
  var _CM_MAX_SIDE = 1280;
  var _CM_JPEG_Q   = 0.85;

  function _compressDataUrl(dataUrl) {
    return new Promise(function (resolve) {
      try {
        var img = new Image();
        img.onload = function () {
          try {
            var w = img.naturalWidth, h = img.naturalHeight;
            if (!w || !h) { resolve(dataUrl); return; }
            var scale = Math.min(1, _CM_MAX_SIDE / Math.max(w, h));
            var dw = Math.round(w * scale), dh = Math.round(h * scale);
            var cv = document.createElement('canvas');
            cv.width = dw; cv.height = dh;
            var ctx = cv.getContext('2d');
            ctx.drawImage(img, 0, 0, dw, dh);
            // Если оригинал PNG с прозрачностью — toDataURL('image/jpeg') её
            // потеряет (фон станет чёрным). Это ок для мессенджера.
            var out = cv.toDataURL('image/jpeg', _CM_JPEG_Q);
            // Если сжатый внезапно тяжелее оригинала (бывает на тонких PNG) —
            // возвращаем оригинал.
            resolve(out.length < dataUrl.length ? out : dataUrl);
          } catch (_e) { resolve(dataUrl); }
        };
        img.onerror = function () { resolve(dataUrl); };
        img.src = dataUrl;
      } catch (_e) { resolve(dataUrl); }
    });
  }

  function _readFilesAsDataUrls(files, remaining) {
    var arr = Array.from(files).slice(0, remaining);
    return Promise.all(arr.map(function (f) {
      return new Promise(function (resolve) {
        var rd = new FileReader();
        rd.onload = function () { resolve(rd.result); };
        rd.onerror = function () { resolve(null); };
        rd.readAsDataURL(f);
      }).then(function (raw) {
        if (!raw) return null;
        return _compressDataUrl(raw);
      });
    })).then(function (results) {
      return results.filter(function (x) { return !!x; });
    });
  }

  window.cmHandleFiles = function (ev) {
    var files = ev.target.files;
    if (!files || !files.length) return;
    if (STATE.images.length >= CM_MAX_IMAGES) {
      if (window.showToast) window.showToast('Максимум ' + CM_MAX_IMAGES + ' фото', 'err');
      ev.target.value = '';
      return;
    }
    var remaining = CM_MAX_IMAGES - STATE.images.length;
    var sendBtn = document.getElementById('cmSendBtn');
    if (sendBtn) sendBtn.disabled = true;
    _readFilesAsDataUrls(files, remaining).then(function (urls) {
      urls.forEach(function (u) {
        if (STATE.images.length < CM_MAX_IMAGES) STATE.images.push(u);
      });
      renderImagesPreview();
      L('FILES', 'loaded=' + urls.length + ' total=' + STATE.images.length);
    }).catch(function (e) {
      L('FILES_FAIL', e.message, 'error');
    }).finally(function () {
      if (sendBtn) sendBtn.disabled = false;
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
    if (!files || !files.length) return;
    if (STATE.postImages.length >= CM_MAX_IMAGES) {
      if (window.showToast) window.showToast('Максимум ' + CM_MAX_IMAGES + ' фото', 'err');
      ev.target.value = '';
      return;
    }
    var remaining = CM_MAX_IMAGES - STATE.postImages.length;
    var btn = document.getElementById('cmPostBtn');
    if (btn) btn.disabled = true;
    _readFilesAsDataUrls(files, remaining).then(function (urls) {
      urls.forEach(function (u) {
        if (STATE.postImages.length < CM_MAX_IMAGES) STATE.postImages.push(u);
      });
      renderPostImagesPreview();
    }).finally(function () { if (btn) btn.disabled = false; });
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
    var pane = document.getElementById('cmPostsPane');
    if (!list) return;
    return http('GET', '/api/community/posts?limit=30').then(function (data) {
      // M3.5.2: бэк отдаёт DESC (новые первые) — переворачиваем, чтобы лента
      // постов шла как чат: старые сверху, новые снизу. После рендера
      // прокручиваем pane вниз, чтобы юзер сразу видел свежий пост.
      var posts = (data.posts || []).slice().reverse();
      if (!posts.length) {
        list.innerHTML = '<div style="color:#666;text-align:center;padding:30px 0">Постов пока нет.</div>';
        return;
      }
      list.innerHTML = '';
      posts.forEach(function (m) {
        STATE.msgsCache[m.id] = m;
        list.appendChild(renderMessage(m));
      });
      if (pane) requestAnimationFrame(function () { pane.scrollTop = pane.scrollHeight; });
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
    cmConfirm('Отвязать Telegram от уведомлений?', function () {
      http('DELETE', '/api/community/tg_link').then(function (s) {
        STATE.tgState = s; renderTgChip(s); renderTgModal(s);
      }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
    });
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
        // M3.5.2: инкрементальный poll — без сноса DOM, без сбоя scroll'а.
        if (STATE.tab === 'chat') loadMessagesPoll();
      } else {
        clearInterval(STATE.pollTimer); STATE.pollTimer = null;
        stopParticles();
      }
    }, 8000);
    // M3.5.2: один раз привязываем scroll-listener — он сам гасит chip,
    // когда юзер сам доскроллил вниз.
    _bindChatScrollListener();
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

  // ── Кастомный диалог (замена window.confirm/prompt/alert) ──────────
  function showCmDialog(opts) {
    var ov = document.getElementById('cmDialogOverlay');
    var titleEl = document.getElementById('cmDialogTitle');
    var msgEl   = document.getElementById('cmDialogMsg');
    var inp     = document.getElementById('cmDialogInput');
    var cancelB = document.getElementById('cmDialogCancel');
    var okB     = document.getElementById('cmDialogOk');
    if (!ov || !titleEl || !msgEl || !inp || !cancelB || !okB) {
      // fallback: если HTML ещё не загружен
      if (opts.showInput) {
        var v = window.prompt(opts.message, opts.defaultVal || '');
        if (v !== null && opts.onOk) opts.onOk(v);
      } else {
        if (opts.showCancel) {
          if (window.confirm(opts.message) && opts.onOk) opts.onOk(null);
          else if (opts.onCancel) opts.onCancel();
        } else {
          window.alert(opts.message);
          if (opts.onOk) opts.onOk(null);
        }
      }
      return;
    }
    titleEl.textContent = opts.title || '';
    msgEl.textContent   = opts.message || '';
    if (opts.showInput) {
      inp.style.display = 'block';
      inp.value = opts.defaultVal || '';
      setTimeout(function() { inp.focus(); inp.select(); }, 80);
    } else {
      inp.style.display = 'none';
    }
    cancelB.style.display = opts.showCancel ? '' : 'none';
    ov.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    function close() {
      ov.style.display = 'none';
      document.body.style.overflow = '';
    }
    cancelB.onclick = function () { close(); if (opts.onCancel) opts.onCancel(); };
    okB.onclick = function () {
      var val = opts.showInput ? inp.value : null;
      close();
      if (opts.onOk) opts.onOk(val);
    };
    inp.onkeydown = function (e) {
      if (e.key === 'Enter') { okB.click(); }
      if (e.key === 'Escape') { cancelB.click(); }
    };
  }

  function cmConfirm(message, onOk, onCancel) {
    showCmDialog({title: 'Подтверждение', message: message, showInput: false, showCancel: true, onOk: onOk, onCancel: onCancel});
  }
  function cmPrompt(message, defaultVal, onOk) {
    showCmDialog({title: 'Введите данные', message: message, showInput: true, defaultVal: defaultVal, showCancel: true, onOk: function (v) { if (v !== null) onOk(v); }});
  }
  function cmAlert(title, message, onOk) {
    showCmDialog({title: title, message: message, showInput: false, showCancel: false, onOk: onOk});
  }

  // ── Mute toggle для раздела «Уведомления» ──────────────────────────
  window.cmToggleMuteFromToggle = function (checked) {
    http('POST', '/api/community/mute_mentions', {mute: !!checked})
      .then(function (r) {
        STATE.muteMentions = !!r.mute;
        window.cmSyncNotifMuteToggle && window.cmSyncNotifMuteToggle();
      })
      .catch(function (e) { if (window.showToast) window.showToast(e.message, 'err'); });
  };

  window.cmSyncNotifMuteToggle = function () {
    var toggle = document.getElementById('notifMuteToggle');
    var card   = document.getElementById('notifMuteCard');
    if (toggle) toggle.checked = STATE.muteMentions;
    if (card) card.style.display = STATE.isAuth ? 'flex' : 'none';
  };

  L('MOD', 'community.js loaded (M3.2 refactor)');
})();
