# FreeAI Python — Бесплатный AI API Gateway

Бесплатный API-шлюз для доступа к моделям Gemini через Telegram-мост.
Включает веб-интерфейс с системой отзывов, AI-модерацией, поддержкой,
уведомлениями и dual-mode для Telegram-аккаунтов.

## Возможности

- REST API, совместимый с OpenAI-форматом (`/api/v1/chat`).
- 11 моделей Gemini (Flash, Thinking, Robotics и др.) с реальной статистикой
  использования (`totalRequests`, `supportsVision`).
- Vision-поддержка (отправка изображений).
- Управление API-ключами (создание, переименование, мягкое удаление,
  регенерация, история запросов, скачивание Telethon-сессии).
- Имитация SSE-стриминга (`"stream": true` — ответ приходит побуквенно
  после получения от ИИ).
- Реальная статистика из SQLite (пользователи, запросы, модели), без
  фейковых маркетинговых цифр.
- Mobile-first фронтенд без Node.js / Rust / C++ зависимостей.
- Подробные лог-коды для отладки.
- Система отзывов с лайками, средним баллом (avg_score) и Smart Drafts
  (автосохранение черновика на клиенте).
- AI-модерация отзывов (`FavoriteAIAgent`): автоматические действия
  APPROVE / FEEDBACK / DELETE с публичным ответом и админ-отчётом.
- Поддержка пользователей через Favorite AI Agent с doc-тегами
  (агент ссылается на разделы внутренней документации).
- Уведомления, сгруппированные по типам (`review` / `support` / `system`),
  с фильтром-вкладками и счётчиками непрочитанных.
- Чат сообщества (раздел «Чат» в меню): общий чат всех пользователей
  + лента постов администрации. Telegram-style порядок (старые сверху,
  новые снизу), polling каждые 8 сек с инкрементальной подгрузкой
  без сноса DOM, chip «↓ N новых» если юзер скроллил вверх. Реакции
  по одному эмодзи на пользователя (включая кастомные `:name:`),
  ответы со свайпом и цитатой, @упоминания с TG-уведомлениями,
  закреп админом, история правок, бан в чате на N дней с причиной.
  До 10 фото на сообщение (клиентское сжатие до 1280px / JPEG q=0.85,
  серверный лимит 2.5 MB на фото).
- Dual-mode: два привязанных Telegram-аккаунта (основной + переводчик).
- Система памяти агента (`agent_memory`: `context_md`, `favorite_md`)
  с механизмом `pending_restore` после `/reset`.
- Ring-buffer логов в памяти + дамп в `logi.txt`.

## Быстрый старт

### Установка (Termux / Linux)

```bash
git clone https://github.com/animebyst07-stack/FreeApi-Python.git
cd FreeApi-Python
pip install -r requirements.txt
```

### Настройка

```bash
cp .env.example .env
# Отредактируйте .env — укажите SESSION_SECRET
```

### Самопроверка установки

```bash
python check_env.py
```

Скрипт проверит Python-библиотеки, `.env`, SQLite-базу, Flask health-check,
порт `5000` и доступность Telegram через Telethon. Если есть `[X]`,
исправьте указанную проблему и запустите проверку снова.

### Запуск

```bash
python api.py
```

Сервер запустится на `http://0.0.0.0:5000` (или порт из `.env`).

## API Endpoints

### Базовое / авторизация
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/healthz` | Проверка здоровья |
| POST | `/api/auth/register` | Регистрация |
| POST | `/api/auth/login` | Вход |
| POST | `/api/auth/logout` | Выход |
| GET | `/api/auth/me` | Текущий пользователь |
| GET | `/api/log-codes` | Справочник лог-кодов |
| GET | `/api/stats/global` | Глобальная статистика |
| GET | `/api/models` | Список моделей (`totalRequests`, `supportsVision`) |

### Чат / API v1 (Bearer)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/v1/chat` | Запрос к ИИ. Добавь `"stream":true` для SSE-имитации. Поле `model` опционально (берётся `default_model` ключа) |
| POST | `/api/v1/stop` | Прервать TG-запрос (актуально при streaming) |
| POST | `/api/v1/reset` | Сброс контекста диалога. При CTX_LIMIT_180 вернёт `requires_choice` |
| POST | `/api/v1/reset/apply` | Применить выбор `save` / `discard` после `requires_choice` |
| GET  | `/api/v1/me` | Контекст ключа за один запрос (имя, модель, context_kb, лимиты, владелец, статистика) |
| GET  | `/api/v1/models` | Каноничный список моделей под ключ + `keyDefaultModelId` + `recommended` |

### Внутренний чат (cookie-сессия, для веб-UI)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/chat/test` | Тестовый прогон из встроенного чата (не Bearer) |
| POST | `/api/chat/reset` | Сброс контекста из встроенного чата |
| POST | `/api/chat/reset/apply` | Применение выбора после `requires_choice` |

### Telegram-мост
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/tg/setup` | Создать сессию настройки Telegram |
| POST | `/api/tg/setup/:id/code` | Ввести код подтверждения |
| GET | `/api/tg/setup/:id/status` | Статус настройки (JSON или SSE) |
| POST | `/api/tg/setup/:id/retry` | Повторить упавший шаг |
| POST | `/api/tg/setup/:id/cancel` | Отменить настройку |
| POST | `/api/tg/session/import` | Загрузить готовый `.session`-файл Telethon (StringSession base64 / SQLite) |
| DELETE | `/api/tg/account` | Удалить Telegram-аккаунт |

### API-ключи
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/keys` | Список API-ключей |
| POST | `/api/keys` | **Всегда 409**: ключ создаётся как побочный эффект `/api/tg/setup` (см. ниже), прямого создания нет |
| GET | `/api/keys/:id` | Детали ключа + история запросов |
| PUT | `/api/keys/:id` | Обновить `name` / `defaultModel` / `skipHints` / `dualMode` / `translatorAccountId` |
| DELETE | `/api/keys/:id` | Деактивировать ключ (мягкое удаление, `is_active=0`) |
| POST | `/api/keys/:id/regen` | Перегенерировать значение ключа (`rawKey` показывается один раз) |
| GET | `/api/keys/:id/logs` | История запросов по ключу |
| GET | `/api/keys/:id/session` | Скачать Telethon-сессию (.session / .txt) |

### Отзывы
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/reviews` | Лента отзывов (одобренные) |
| POST | `/api/reviews` | Создать отзыв (оценка 1–10, текст, изображения) |
| GET | `/api/reviews/mine` | Свой отзыв (для проверки уникальности) |
| POST | `/api/reviews/:id/like` | Поставить/снять лайк |
| DELETE | `/api/reviews/:id` | Удалить свой отзыв |

### Уведомления
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/notifications` | Список + `unread_by_kind` (фильтр `?kind=`) |
| POST | `/api/notifications/read_all` | Отметить прочитанным (опц. `?kind=`) |
| POST | `/api/notifications/:id/read` | Отметить одно прочитанным |
| DELETE | `/api/notifications/:id` | Удалить |

### Поддержка
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/support/chat` | Текущий открытый диалог поддержки |
| POST | `/api/support/chat` | Отправить сообщение / создать диалог |
| GET | `/api/support/chat/stream` | SSE-поток ответов AI-агента |
| POST | `/api/support/close` | Закрыть диалог (создаёт админ-отчёт) |

### Чат сообщества (cookie-сессия)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/community/state` | Авторизация / админ-флаг / бан / mute |
| GET | `/api/community/messages` | Лента сообщений (`limit`, `before_id` для older) |
| POST | `/api/community/messages` | Отправить (`text`, `images`, `reply_to_id`) |
| POST | `/api/community/messages/:id/react` | Поставить/снять эмодзи (Telegram-style: один на юзера) |
| GET | `/api/community/messages/:id/versions` | История правок сообщения |
| POST | `/api/community/messages/:id/pin` | Закрепить (админ) |
| GET | `/api/community/posts` | Лента постов администрации |
| POST | `/api/community/posts` | Опубликовать пост (только админ) |
| POST | `/api/community/bans` | Забанить юзера в чате на N дней (админ) |
| GET | `/api/community/tg_link` | Состояние TG-привязки для уведомлений |
| GET | `/api/community/emojis` | Список кастомных эмодзи (`:name:`) |

### Администрирование (только `ReZero`)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/admin/settings` | Текущие настройки |
| PUT | `/api/admin/settings` | Обновить настройки |
| GET | `/api/admin/notifications` | Лента админских уведомлений |
| GET | `/api/admin/support/chat/:id` | Полная переписка диалога поддержки |

## Пример запроса

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/chat" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.0-flash-thinking",
    "messages": [{"role": "user", "content": "Привет!"}]
  }'
```

## Статистика

Блок статистики на главной странице показывает **реальные данные** из SQLite:
- Количество зарегистрированных пользователей.
- Запросы за сегодня.
- Общее количество запросов.
- Количество доступных моделей.

На пустой базе отображаются нули — никаких фейковых маркетинговых цифр.

## Зависимости

- Python 3.11+ (используется современный синтаксис).
- Flask 3.0.3.
- Telethon 1.36.0.
- SQLite (встроен в Python).

Без Rust, C++ или Node.js зависимостей. Полностью совместимо с Termux.

## Структура проекта

```
FreeApi-Python/
├── api.py                       # Точка входа
├── freeapi/
│   ├── app.py                   # Flask-приложение, регистрация blueprints
│   ├── agent.py                 # FavoriteAIAgent (модерация отзывов)
│   ├── auth_service.py          # Регистрация / логин
│   ├── config.py                # Конфигурация
│   ├── database.py              # SQLite схема и подключение
│   ├── log_codes.py             # Справочник лог-кодов
│   ├── models.py                # Список AI-моделей
│   ├── progress.py              # SSE-прогресс настройки TG
│   ├── scheduler.py             # Фоновые задачи
│   ├── security.py              # Шифрование, UUID, ключи
│   ├── support_docs.py          # Внутренняя документация для AI-агента поддержки
│   ├── tg.py                    # Telegram-мост (Telethon)
│   ├── repositories.py          # Backwards-compat shim (re-export из repos/)
│   ├── repos/                   # Модульные репозитории (шаг 0.3)
│   │   ├── admin.py
│   │   ├── keys.py
│   │   ├── notifications.py
│   │   ├── reviews.py
│   │   ├── stats.py
│   │   ├── support.py
│   │   ├── tg_accounts.py
│   │   └── users.py
│   ├── blueprints/              # Flask-blueprints по доменам
│   │   ├── auth_bp.py
│   │   ├── keys_bp.py
│   │   ├── notifications_bp.py
│   │   ├── reviews_bp.py
│   │   ├── support_bp.py
│   │   ├── admin_bp.py
│   │   └── tg_bp.py
│   └── migrations/              # Идемпотентные SQL-миграции (001..NNN)
├── static/
│   ├── index.html               # Главный HTML-каркас
│   ├── css/main.css             # Стили (mobile-first)
│   └── js/                      # Модульный фронтенд (ESM)
│       ├── core/                # api, dom, общие утилиты
│       └── views/               # Экраны: keys, reviews, notifications, ...
├── check_env.py                 # Самопроверка установки для Termux/Linux
├── requirements.txt
├── .env.example
├── plan.txt                     # Текущий план задач (синхронизируется с агентом)
└── README.md
```
