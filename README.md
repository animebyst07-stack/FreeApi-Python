# FreeAI Python — Бесплатный AI API Gateway

Бесплатный API-шлюз для доступа к моделям Gemini через Telegram-бридж.

## Возможности

- REST API совместимый с OpenAI-форматом
- 11 моделей Gemini (Flash, Thinking, Robotics и др.)
- Vision-поддержка (отправка изображений)
- Управление API-ключами
- Реальная статистика из SQLite (пользователи, запросы, модели)
- Mobile-first фронтенд без Node.js зависимостей
- Подробные лог-коды для отладки
- Имитация SSE-стриминга (`"stream": true` — ответ приходит побуквенно после получения от ИИ)

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

Скрипт проверит Python-библиотеки, `.env`, SQLite-базу, Flask health-check, порт `5000` и доступность Telegram через Telethon. Если есть `[X]`, исправьте указанную проблему и запустите проверку снова.

### Запуск

```bash
python api.py
```

Сервер запустится на `http://0.0.0.0:5000` (или порт из `.env`)

## API Endpoints

| Метод | Путь | Описание |
  |-------|------|----------|
  | GET | `/api/healthz` | Проверка здоровья |
  | POST | `/api/auth/register` | Регистрация |
  | POST | `/api/auth/login` | Вход |
  | POST | `/api/auth/logout` | Выход |
  | GET | `/api/auth/me` | Текущий пользователь |
  | GET | `/api/models` | Список моделей |
  | GET | `/api/stats/global` | Глобальная статистика |
  | GET | `/api/log-codes` | Справочник лог-кодов |
  | **POST** | `/api/v1/chat` | Запрос к ИИ. Добавь `"stream":true` для SSE-имитации стриминга |
  | POST | `/api/v1/stop` | Прервать TG-запрос (актуально при streaming) |
  | POST | `/api/v1/reset` | Сброс контекста диалога |
  | POST | `/api/tg/setup` | Создать сессию настройки Telegram |
  | POST | `/api/tg/setup/:id/code` | Ввести код подтверждения Telegram |
  | GET | `/api/tg/setup/:id/status` | Статус настройки (JSON или SSE-поток) |
  | POST | `/api/tg/setup/:id/retry` | Повторить упавший шаг настройки |
  | POST | `/api/tg/setup/:id/cancel` | Отменить настройку |
  | DELETE | `/api/tg/account` | Удалить Telegram-аккаунт |
  | GET | `/api/keys` | Список API-ключей |
  | POST | `/api/keys` | Создать API-ключ |
  | GET | `/api/keys/:id` | Детали ключа + история запросов |
  | PUT | `/api/keys/:id` | Обновить имя / модель / skipHints |
  | DELETE | `/api/keys/:id` | Деактивировать ключ |
  | POST | `/api/keys/:id/regen` | Перегенерировать значение ключа |
  | GET | `/api/keys/:id/logs` | История запросов по ключу |
  | GET | `/api/keys/:id/session` | Скачать Telethon-сессию (.session / .txt) |

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
- Количество зарегистрированных пользователей
- Запросы за сегодня
- Общее количество запросов
- Количество доступных моделей

На пустой базе отображаются нули — никаких фейковых маркетинговых цифр.

## Зависимости

- Flask 3.0.3
- Telethon 1.36.0
- Python 3.8+
- SQLite (встроен в Python)

Без Rust, C++ или Node.js зависимостей. Полностью совместимо с Termux.

## Структура проекта

```
FreeApi-Python/
├── api.py              # Точка входа
├── freeapi/
│   ├── app.py          # Flask-приложение
│   ├── auth_service.py # Регистрация/логин
│   ├── config.py       # Конфигурация
│   ├── database.py     # SQLite схема и подключение
│   ├── log_codes.py    # Справочник лог-кодов
│   ├── models.py       # Список AI-моделей
│   ├── progress.py     # SSE-прогресс настройки
│   ├── repositories.py # Запросы к БД
│   ├── scheduler.py    # Фоновые задачи
│   ├── security.py     # Шифрование и ключи
│   └── tg.py           # Telegram-мост
├── static/
│   └── index.html      # Фронтенд (self-contained)
├── check_env.py        # Самопроверка установки для Termux/Linux
├── requirements.txt
├── .env.example
└── README.md
```
