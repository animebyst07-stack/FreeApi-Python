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
| 0.5.7    | ☐      | —        | следующий: вынос UI-помощников (`showToast/openModal/closeModal/...`) и/или другой блок по `plan.txt` |

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
