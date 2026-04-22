/* main.js — entry-point модульной фронтенд-сборки.
   Шаг 0.5.1: только импорты-заглушки + проверка загрузки бандла.
   Реальная логика будет переносится в подшагах 0.5.2 .. 0.5.7. */

import './core/api.js';
import './core/logger.js';
import './core/storage.js';
import './core/dom.js';
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

/* Маркер, что ESM-бандл загружен (для smoke-теста через DevTools). */
window.__FPA_MAIN_LOADED__ = true;
console.debug('[FPA] main.js loaded (step 0.5.1 stub)');
