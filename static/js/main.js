/* main.js — entry-point модульной фронтенд-сборки.
   ВНИМАНИЕ ПО ПОРЯДКУ ЗАГРУЗКИ:
   <script type="module"> исполняется в режиме defer, ПОСЛЕ парсинга DOM
   и ПОСЛЕ всех inline classic-<script>. Поэтому нельзя выставлять отсюда
   window.X для функций, нужных синхронно — inline IIFE упадёт с
   ReferenceError. Такие хелперы остаются продублированы в inline-скрипте
   до момента, когда сам IIFE будет перенесён в модуль. */

import './core/dom.js';     // q/esc/formatDate (для будущих ESM-консументов)
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

window.__FPA_MAIN_LOADED__ = true;
console.debug('[FPA] main.js loaded (step 0.5.2 hotfix: ESM-инфраструктура без вытеснения inline)');
