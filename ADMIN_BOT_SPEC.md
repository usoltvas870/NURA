# Admin Bot — спецификация

## Концепция

Отдельный Telegram-бот для наблюдения и ограниченных оперативных действий через чат.
Бот читает состояние контейнеров, информирует администратора и выполняет только
явно разрешённые runtime-операции.

## Принципы безопасности

1. Бот доступен только по whitelist telegram_id (админ)
2. Бот не изменяет source checkout и не собирает production release
3. Автофикс разрешён только для безопасных операций:
   - перезапуск контейнера
   - очистка кэша Redis
   - перезапуск Celery worker
4. Production deploy разрешён только через approved manual GitHub Actions workflow
5. Secrets никогда не попадают в логи и сообщения

## Команды

```
/status        — сводка: все контейнеры, health, последние ошибки
/restart [svc] — перезапустить контейнер (api|bot|celery-worker|celery-beat)
/cache clear   — очистить Redis кэш
/help          — список команд
```

Admin Bot не выполняет source checkout, production build или deploy. В нём нет
production-deploy command или deployment service method.

## Авто-мониторинг (Celery)

Задача `monitor_health` каждые 5 минут:
1. Проверяет `/health` на 200
2. Docker ps — все контейнеры running/healthy?
3. Сканирует логи за 5 минут на ERROR/CRITICAL/FATAL/Exception
4. Если проблема → отправляет админу:
   ```
   ⚠️ NURA Health Alert
   Контейнер: api — unhealthy
   Ошибка: ConnectionError в payment_webhook
   Traceback: …
   Действия: /restart api | /errors 20 | /cache clear
   ```

## Схема работы

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Telegram   │────▶│  Admin Bot   │────▶│  Admin API   │
│  (админ)    │◀────│  (aiogram)   │◀────│  /logs /stats │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
                    ┌──────▼───────┐
                    │ Docker socket│
                    │ (напрямую)   │
                    └──────────────┘

┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Celery Beat │────▶│ Celery Worker│────▶│  Admin Bot   │
│ (5 min)     │     │ monitor_health│    │  send_msg()  │
└─────────────┘     └──────────────┘     └──────────────┘
```

## Файлы

```
nura_app/
├── admin_bot/
│   ├── __init__.py
│   ├── main.py              # точка входа, polling
│   ├── config.py            # токен бота, whitelist telegram_id
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── status.py        # /status
│   │   ├── restart.py       # /restart
│   │   ├── cache.py         # /cache clear
│   │   ├── help.py          # /help
│   │   └── chat.py          # текстовые status/restart/cache запросы
│   ├── services/
│   │   ├── docker_client.py # inspection/logs/restart через Docker socket
│   │   ├── log_parser.py    # парсинг логов
│   │   └── ai_advisor.py    # DeepSeek анализ ошибок
│   └── middleware.py        # проверка admin telegram_id
├── core/tasks/
│   └── monitor_health.py    # Celery задача авто-мониторинга
├── core/config.py           # + admin_bot_token, admin_telegram_id
└── docker-compose.yml       # + admin-bot контейнер (опционально)
```

## Нужно создать в BotFather

1. `/newbot` → `@nura_admin_bot`
2. Скопировать токен
3. `/setcommands`:
   ```
   status - Сводка состояния сервера
   restart - Перезапустить сервис
   cache - Управление кэшем
   help - Справка
   ```

## Docker (опционально)

Можно запустить в отдельном контейнере, а можно — как ещё один
процесс в existing bot-контейнере.

**Вариант А — отдельный контейнер:**
```yaml
admin-bot:
  build: .
  command: python -m admin_bot.main
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  env_file: .env
  depends_on: [api]
```

**Вариант Б — в existing bot-контейнере:**
Просто добавить второй процесс. Проще, но смешивает логи.

Рекомендация: вариант Б для простоты, т.к. нагрузка минимальна.

## .env переменные

```
ADMIN_BOT_TOKEN=7xxxxx:xxxxxxxxxxxxxxxxxxxx
ADMIN_TELEGRAM_ID=123456789
```

## Порядок реализации

1. `core/config.py` — добавить `admin_bot_token`, `admin_telegram_id`
2. `admin_bot/` — базовый бот с middleware проверки admin_id
3. `/status` — health check через Docker socket + Admin API
4. `/errors` + `/logs` — чтение логов + AI-анализ ошибок
5. `/restart` — перезапуск контейнера
6. Celery задача `monitor_health` — фоновый мониторинг
7. Интеграция с DeepSeek для анализа ошибок
8. Тестирование
