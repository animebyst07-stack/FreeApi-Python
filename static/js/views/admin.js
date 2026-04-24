/* views/admin.js — раздел «Администрирование».
 *
 * Шаг 0.5.13: основная админ-логика (загрузка ключей/настроек/моделей)
 * пока живёт inline в static/index.html (loadAdmin/saveModeratorSettings/…).
 * Здесь добавляем ТОЛЬКО управление списком админов (M2/блок 6.1.1):
 * GET/POST/DELETE /api/admin/admins. Назначать/снимать может только
 * суперадмин (ReZero).
 *
 * Логирование подробное — категория ADM_*.
 */
(function () {
  'use strict';

  function L(tag, msg, level) {
    try { if (window.clog) window.clog('ADM_' + tag, msg, level || 'info'); } catch (_) {}
    try { console.log('[ADM][' + tag + ']', msg); } catch (_) {}
  }

  function http(method, url, body) {
    L('HTTP', method + ' ' + url);
    return fetch(url, {
      method: method, credentials: 'include',
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.text().then(function (t) {
        var d = null;
        try { d = t ? JSON.parse(t) : {}; } catch (_) { d = {raw: t}; }
        if (!r.ok) {
          L('HTTP_ERR', method + ' ' + url + ' → ' + r.status, 'error');
          var e = new Error((d && d.message) || ('HTTP ' + r.status));
          e.status = r.status; throw e;
        }
        return d;
      });
    });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderList(admins, isSuper) {
    var box = document.getElementById('adminAdminsList');
    var addBlock = document.getElementById('adminAdminsAddBlock');
    if (!box) return;
    if (!admins.length) {
      box.innerHTML = '<div style="color:#666;font-size:12px">Нет ни одного администратора (что-то пошло не так — должен быть ReZero).</div>';
    } else {
      box.innerHTML = admins.map(function (a) {
        var badge = a.is_super
          ? '<span style="font-size:10px;background:#3a2a00;color:#ffc56a;padding:1px 6px;border-radius:4px;margin-left:6px">SUPER</span>'
          : '';
        var rm = (isSuper && !a.is_super)
          ? '<button class="btn btn-ghost btn-xs" style="font-size:10px;color:#c88" onclick="adminRemoveAdmin(\'' + esc(a.user_id) + '\',\'' + esc(a.username) + '\')">снять</button>'
          : '';
        return '<div style="display:flex;align-items:center;justify-content:space-between;background:#0e0e0e;border:1px solid #1c1c1c;border-radius:8px;padding:6px 10px">' +
          '<div><b style="color:#eee">@' + esc(a.username) + '</b>' + badge +
          (a.granted_at ? '<span style="color:#666;font-size:11px;margin-left:8px">с ' + esc(a.granted_at).slice(0, 10) + '</span>' : '') +
          '</div>' + rm + '</div>';
      }).join('');
    }
    if (addBlock) addBlock.style.display = isSuper ? '' : 'none';
  }

  window.loadAdminAdmins = function () {
    L('LOAD', 'enter');
    return http('GET', '/api/admin/admins').then(function (d) {
      L('LOAD_OK', 'count=' + (d.admins || []).length + ' super=' + d.is_super);
      renderList(d.admins || [], !!d.is_super);
    }).catch(function (e) {
      L('LOAD_FAIL', e.message, 'error');
      var box = document.getElementById('adminAdminsList');
      if (box) box.innerHTML = '<div style="color:#c66;font-size:12px">Не удалось загрузить: ' + esc(e.message) + '</div>';
    });
  };

  window.adminAddAdmin = function () {
    var inp = document.getElementById('adminAddInput');
    if (!inp) return;
    var u = (inp.value || '').trim();
    if (!u) return;
    L('GRANT_REQ', 'user=' + u);
    http('POST', '/api/admin/admins', {username: u}).then(function () {
      inp.value = '';
      if (window.showToast) window.showToast('Админ добавлен', 'ok');
      window.loadAdminAdmins();
    }).catch(function (e) {
      L('GRANT_FAIL', e.message, 'error');
      if (window.showToast) window.showToast(e.message, 'err');
    });
  };

  window.adminRemoveAdmin = function (uid, uname) {
    if (!confirm('Снять админ-роль с @' + uname + '?')) return;
    L('REVOKE_REQ', 'user_id=' + uid);
    http('DELETE', '/api/admin/admins/' + encodeURIComponent(uid)).then(function () {
      if (window.showToast) window.showToast('Снято', 'ok');
      window.loadAdminAdmins();
    }).catch(function (e) {
      L('REVOKE_FAIL', e.message, 'error');
      if (window.showToast) window.showToast(e.message, 'err');
    });
  };

  // Хук в существующий loadAdmin (он inline в index.html). Если уже есть —
  // оборачиваем, чтобы дозагрузить наш виджет; иначе ставим как глобал.
  var prev = window.loadAdmin;
  window.loadAdmin = function () {
    try { if (typeof prev === 'function') prev.apply(this, arguments); } catch (e) { console.warn('[ADM] prev loadAdmin failed', e); }
    try { window.loadAdminAdmins(); } catch (e) { console.warn('[ADM] loadAdminAdmins failed', e); }
  };

  L('MOD', 'admin.js loaded (admins-mgmt)');
})();
