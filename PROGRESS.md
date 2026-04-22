# PROGRESS — FreeApi-Python

> Постоянный трекер прогресса по `plan.txt`.
> Агент обязан обновлять файл после **каждого** завершённого шага:
> отметить ✓/✗, написать коммит-хеш, перечислить файлы и заметки.

## ШАГ 0.5 — Вынос JS из `static/index.html` в ESM-модули

| Шаг      | Статус | Коммит   | Что сделано / заметки |
|----------|--------|----------|------------------------|
| 0.5.1    | ✓      | —        | Заглушки модулей `static/js/core/*.js`, `main.js` |
| 0.5.2    | ✓      | —        | ESM-инфраструктура подключена; HOTFIX: `q/esc/formatDate` оставлены в inline (IIFE падал на defer-порядке) |
| 0.5.3a   | ✓      | 5c7f7f6  | Снята обёртка большой IIFE (1529→4150) для будущего ESM-выноса |
| 0.5.4    | ✓      | b87be61  | `window.clog` → `core/logger.js` |
| HOTFIX-A | ✓      | a449cf1  | Лайтбокс: открытие по клику на миниатюру в отзывах |
| 0.5.5    | ✓      | 13df55d  | `function api()` (XHR-обёртка) → `core/api.js`; 51 callsite сохранён |
| **0.5.6**| ✓      | (этот)   | `localStorage`-обёртки → `core/storage.js`: `lsGet/lsSet/lsDel` + `window.*`. Заменены 6 inline-вызовов в `static/index.html` (chat history × 2, review draft × 4). Ключи AS IS. Inline-handler в textarea имеет fallback `window.lsSet \|\| localStorage.setItem` на случай раннего ввода до загрузки ESM. |
| 0.5.7    | ✓      | 90dfb7d  | `showToast` → `ui/toast.js` |
| 0.5.8    | ✓      | ff87601  | `openModal/closeModal/overlayClick/switchModal/customConfirm/resolveConfirm` + `_confirmResolve` → `ui/modal.js` |
| 0.5.9    | ✓      | 2868137  | `toggleSidebar/closeSidebar` + resize-listener → `ui/sidebar.js` |
| 0.5.10   | ✓      | 8b47a98 / 24331bf | `toggleCustomSelect/buildCustomSelect` + click-outside → `ui/select.js` |
| 0.5.11   | ✓      | ff4d049  | `goView` + `updateSidebarActive` (роутер view'ов) → `ui/view.js`. Все view-init функции (`loadDashboard/initChatView/...`) пока остаются inline (top-level classic-script ⇒ window.*). |
| 0.5.12   | ✓      | fbcf8ceb | Уведомления: `refreshNotifBadge/loadNotifications/markAllNotifsRead/deleteUserNotification/startNotifPolling/stopNotifPolling/loadUserNotifications` + `_notifPollTimer/_notifLastUnread` → `views/notifications.js`. Прямой вызов `loadUserNotifications()` в `loadDashboard` заменён на `if(window.refreshNotifBadge) window.refreshNotifBadge();`. |
| 0.5.13-FIX | ✓    | c8647e8 / 23ee193 | HOTFIX bootstrap → DOMContentLoaded. Раньше inline `loadModels()` падал на `api is not defined` и валил остаток скрипта (отсюда `rvAdminDelete is not defined` и пустой раздел «Модели»). Добавлены лог-каналы [BOOT], [ESM], [JS_PROMISE_REJECT]. |
| 0.5.13-UI  | ✓    | (этот) | (а) Удалена дублирующая карточка «Отзывы» из админки (HTML + `_adminReviewImgs/renderAdminReviews/removeAdminReviewImg/onAdminReviewFilesSelected/saveAdminReviewResp/deleteAdminReview/setReviewStatus`). Все действия делаются прямо в разделе «Отзывы». (б) `api.py`: ring-buffer in-memory логов (50k записей, root logger) + сохранение в `/storage/emulated/0/Цхранилище/Мусор/logi.txt` при остановке (Ctrl+C / SIGTERM / atexit). Старый файл удаляется. Fallback в `./logi.txt` при ошибке записи. |
| 0.5.13   | ✓      | (этот)   | Блок поддержки вынесен в `static/js/views/support.js`: `initSupportView/loadSupportHistory/appendSupportMsg/appendSupportThinking/sendSupportMessage/closeSupportChat/_doCloseSupportChat/startNewSupportDialog/onSupportFileSelected/clearSupportAttachment` + локальные `_supportPending/_supportImageBase64/_supportImageName`. Из `static/index.html` удалён весь inline-блок (~205 строк, 3544..3749). Все публичные функции продолжают быть доступны через `window.*` для inline-onclick. Зависимости (`parseTgMarkdown`, `autoResizeTextarea`, `user`, `customConfirm`, `showToast`, `api`) берутся через `window.*` — порядок `defer`-загрузки сохраняется (модуль читает их в момент вызова, не на инициализации). |
| 0.5.14   | ☐      | —        | следующий по плану — `0.5b auth + dashboard` (login/register/logout, loadDashboard) → `views/auth.js`. |

## Оставшиеся подшаги 0.5 (по `plan.txt`)

| Подшаг | Содержимое | Статус |
|--------|-----------|--------|
| 0.5a — core    | api/dom/logger/storage/state | ✓ (0.5.4–0.5.6) |
| 0.5b — auth + dashboard | login/register/logout, loadDashboard | ☐ |
| 0.5c — setup   | Telegram-аккаунты, выдача ключей | ☐ |
| 0.5d — reviews | большой блок отзывов (~700 строк inline) | ☐ |
| 0.5e — chat + support | тестовый чат + поддержка (~500 строк) | ☐ |
| 0.5f — notifications + admin | notifications ✓ (0.5.12); админка ☐ |
| 0.5g — docs + models + main.js + чистка inline-JS | финал | ☐ |

**Итого до конца Шага 0.5: ~6 крупных подшагов.** Дальше по `plan.txt`:
0.6 миграции · 0.7 единое логирование · 0.8 rate-limit · 1.1 push · 1.2 SSE
· 1.3 группировка уведомлений · 1.4 драфты · 1.5 bulk-админка.

## Smoke-тест 0.5.6

После `git pull && python api.py`:
1. Открыть форму «Написать отзыв» — текст из черновика подгружается (если был).
2. Печатать в поле — каждый ввод сохраняет черновик (DevTools → Application → LocalStorage → ключ `freeapi_review_draft`).
3. Отправить отзыв — ключ `freeapi_review_draft` удаляется.
4. Открыть чат — история по ключу `freeapi.chat.<keyId>` подгружается, новые сообщения сохраняются.
5. В DevTools: `typeof window.lsGet === 'function'` → `true`, аналогично `lsSet`, `lsDel`.
6. Главное: 0 `JS_ERROR`, особенно `ReferenceError: lsGet/lsSet/lsDel is not defined`.

## Заметки на будущее

- Ключи в `localStorage` НЕ переименовываются (есть данные у юзеров).
- `core/storage.js` НЕ кладёт префикс `freeapi.` автоматически — обёртки нейтральны.
- При следующем шаге продолжать тот же паттерн: вынос → `window.*` экспорт → замена inline → валидация → push.

## 0.5.13b — Документация по тегам для агента поддержки

**Файлы:** `freeapi/support_docs.py` (новый), `freeapi/blueprints/support_bp.py`, `static/js/views/support.js`.

**Идея.** Вместо того чтобы пихать в Сэма ~300 КБ исходников проекта на каждый
вопрос (как было в `support_project_context()`), даём ему компактный индекс
доступной документации (~700 байт) и инструкцию: «когда нужно — напиши
промежуточный текст и тег `[[doc:NAME]]`, сервер подгрузит». Сэм отвечает
шагами как живой агент.

**Реестр документации** — `freeapi/support_docs.py`, словарь `DOCS` с разделами:
`menu`, `auth`, `api_keys`, `tg_setup`, `models`, `chat`, `reviews`, `support`,
`admin`, `errors`, `stats`, `notifications`. Добавлять новые — просто дописать
ключ в `DOCS` и описание в `DOCS_INDEX_LINES`.

**Цикл резолвинга тегов** в `support_send_message`:
  1. Получили ответ ИИ → ищем `[[doc:NAME]]` регуляркой.
  2. Текст до первого тега = «шаг агента», сохраняем в БД с
     `role='agent_step'` (имена тегов кладём в поле `image_data`,
     для шага оно под картинку всё равно не используется).
  3. Собираем тексты запрошенных доков, шлём Сэму следующее сообщение:
     «=== ДОКУМЕНТАЦИЯ: name === ...\nТеперь отвечай по существу».
  4. До 3 итераций (`_MAX_DOC_ITERATIONS`), потом стоп — оставшиеся теги
     вычищаем из финального ответа.
  5. На `CTX_LIMIT` внутри цикла — `/reset` и отдаём шаг как финальный ответ.

**API ответ** теперь содержит массив `steps`:
```json
{ "user_message": {...}, "steps": [{...}, ...], "agent_message": {...}, "chat": {...} }
```

**Фронт** (`views/support.js`):
  - `appendSupportMsg(role, content, imageSrc, docTag)` — расширили сигнатуру.
  - Для `role==='agent_step'` рисуем компактный пузырь с пунктирной рамкой,
    значком 📖 и текстом «Читаю документацию: **NAME**» + курсив фразы агента.
  - В `loadSupportHistory` и в обработчике ответа `/api/support/chat` —
    проходим `d.steps` и рисуем перед финальным `agent_message`.

**Что критично проверить в Termux:**
  1. `git pull && python api.py`.
  2. Открыть «Поддержка», написать «как оставить отзыв?» → должно
     появиться: пузырь шага «📖 Читаю документацию: reviews» (+ короткая
     фраза от ИИ), затем полноценный ответ.
  3. Открыть DevTools Network → `/api/support/chat` → проверить что в JSON
     есть массив `steps` и финальный `agent_message`.
  4. Перезагрузить страницу — история должна нарисоваться идентично
     (шаги тоже сохранены в БД).
