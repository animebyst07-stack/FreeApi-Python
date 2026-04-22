/* main.js — entry-point модульной фронтенд-сборки.
   После 0.5.2: core/dom.js — чистые утилиты (q, esc, formatDate)
   уже работают через ESM. Остальные модули — заглушки. */

import { q, esc, formatDate } from './core/dom.js';
import './core/api.js';
import './core/logger.js';
import './core/storage.js';
import './core/state.js';

import './ui/toast.js';
import './ui/modal.js';
import './ui/sidebar.js';
import './ui/topbar.js';
import './ui/select.js';
import './ui/view.js';

import './views/auth.js';
import './views/keys.js';
import './views/chat.js';
import './views/reviews.js';
import './views/notifications.js';
import './views/support.js';
import './views/admin.js';
import './views/stats.js';

/* ВРЕМЕННО: пока inline-скрипт в index.html ещё ссылается на эти функции
   через onclick="esc(...)" и аналогичные — экспортируем их в window.
   После полного выноса логики и перевода onclick-ов на addEventListener
   эту строку можно будет удалить (см. шаг 0.5.7-0.5.8). */
window.q = q;
window.esc = esc;
window.formatDate = formatDate;

window.__FPA_MAIN_LOADED__ = true;
console.debug('[FPA] main.js loaded (step 0.5.2: core/dom in module)');
