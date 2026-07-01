# Auth System — оставшиеся задачи

**Версия:** 1.1 (обновлён 01.07.2026)  
**Дата:** 02.07.2026  
**Откуда:** реализация `docs/auth_system_implementation_plan.md` (Фазы 1+2 завершены, 3 реализована)

---

## 🔴 Срочно (до деплоя)

### 1. Применить миграцию на VPS ✅

**Сделано 01.07.2026** — `alembic upgrade head` выполнен внутри контейнера `nura_app-api-1`, миграция `c4d5e6f7a8b9` на head.

Миграция `c4d5e6f7a8b9_add_auth_and_guest.py`:
- Добавляет колонки `phone`, `auth_method`, `email_verified`, `phone_verified`, `vk_id` в `users`
- Создаёт partial unique indexes (`uq_user_email_notnull`, `uq_user_phone_notnull`, `uq_user_vk_id_notnull`)
- Создаёт таблицу `guest_profiles`

### 2. Прописать API-ключи в `.env` на VPS

Статус:
- ✅ `VK_CLIENT_ID`, `VK_CLIENT_SECRET`, `VK_SERVICE_TOKEN` — прописаны
- ❌ `UNISENDER_API_KEY` — **отсутствует**, нужно добавить в `/opt/nura/nura_app/.env`
- ❌ `SMS_RU_API_ID` — не требуется (SMS-аутентификация удалена из кода)

Без `UNISENDER_API_KEY` задача `send_magic_link_email` логирует warning и не отправляет письма.

### 3. ~~Настроить Unisender~~ — заменён на Beget SMTP ✅

Код переписан (коммит `e2c4b32`): `send_magic_link_email` теперь отправляет письма через SMTP Beget (`smtp.beget.com:465`) вместо Unisender API.

Что сделано:
- ✅ SMTP-конфигурация в `core/config.py`
- ✅ HTML-шаблон письма «Вход в NURA» с text/plain fallback
- ✅ `aiosmtplib` добавлен в `requirements.txt`
- ✅ Безопасное логирование (email маскируется, токен не логируется)
- ✅ `UNISENDER_API_KEY` помечен deprecated
- ⬜ `SMTP_PASSWORD` — **пользователь внесёт сам** в `.env` на VPS
- ⬜ Деплой на VPS — ожидается восстановление сервера (SSH недоступен на 01.07.2026)

**Настройки Unisender (SPF/DKIM/DMARC) уже не нужны** — почта идёт напрямую через SMTP Beget, где всё уже настроено.

Старая тема письма: «Ваш персональный отчёт готов». Новая тема: «Вход в NURA».

### 4. ~~Настроить SMS.ru~~ — отменено

SMS-аутентификация полностью удалена из кода (коммиты `318ea10`, `013f5bc`, `7ffe479`). Остались только поля-заглушки в `core/config.py`.

---

## 🟡 Фаза 3 — VK ID (код готов, ключи прописаны)

**Статус:** Код и ключи готовы. Осталось ручное тестирование.

### Что сделано:
- ✅ Создан метод `vk_auth` в `AuthService` (obmen access_token на user info через `id.vk.ru/oauth2/user_info`)
- ✅ Эндпоинт `POST /api/v1/auth/vk` принимает `{access_token, user_id, guest_token?}` → создаёт/находит пользователя по `vk_id`, устанавливает сессию
- ✅ Добавлен виджет VK ID One Tap в `mini.html` (секция `#stage-auth`)
- ✅ Схема `VKTokenRequest` для валидации запроса
- ✅ Ключи прописаны в `.env` на VPS (`VK_CLIENT_ID`, `VK_CLIENT_SECRET`, `VK_SERVICE_TOKEN`)
- ✅ Тесты проходят (19/19)

### Что осталось сделать:
1. **Проверить redirect URL в кабинете VK ID:**
   - Должен быть: `https://nura-ai.ru/api/v1/auth/vk/callback`
   - Если нет — добавить в настройках приложения

2. **Протестировать flow:**
   - Открыть `mini.html` → пройти квиз → на экране авторизации нажать кнопку VK ID
   - Авторизоваться через VK → должно редиректить в `/app/`
   - Проверить, что пользователь создан в БД с `vk_id` и `auth_method='vk'`

### Архитектура VK ID интеграции:
- **Фронтенд:** VK ID SDK (One Tap кнопка) → получает `code` → обменивает на `access_token` через `VKID.Auth.exchangeCode()` → отправляет на бэкенд
- **Бэкенд:** `POST /api/v1/auth/vk` → вызывает `id.vk.ru/oauth2/user_info` → находит/создаёт пользователя → устанавливает сессию
- **Callback:** `https://nura-ai.ru/api/v1/auth/vk/callback` — используется VK ID SDK для postMessage (не требует отдельной страницы)

---

## 🟢 Улучшения (после деплоя)

### 10. Celery Beat — cron для `cleanup_expired_guest_profiles` ✅

- ✅ `nura_app-celery-beat-1` работает на VPS
- ✅ Задача `cleanup-expired-guests` в расписании (раз в сутки)

### 11. Rate limiting — мониторинг

Все эндпоинты `/api/v1/auth/*` уже обёрнуты в slowapi. Через неделю после деплоя:
- Посмотреть логи на предмет 429 ошибок
- Если слишком много — ослабить лимиты в `api/routes/auth.py`
- Если слишком мало — можно закрутить (сейчас лимиты щадящие по плану)

### 12. Мониторинг Sentry

- Убедиться, что ошибки из `AuthService` (логирование через `logger.exception`) попадают в Sentry
- Проверить, что `send_magic_link_email` логирует ошибки при падении Unisender

### 13. UX — повторная отправка письма

Сейчас пользователь не может запросить письмо повторно, пока не истечёт TTL. Можно добавить кнопку «Отправить ещё раз» с таймером обратного отсчёта (60 секунд) на фронтенде (только Email, SMS удалён).

### 14. ~~A/B тест Email vs SMS~~ — отменено

SMS-аутентификация удалена. A/B тест нерелевантен.

---

## 🔵 Фаза 4 — продуктовые (когда будет готова аналитика)

- Реферальная программа через Telegram-бот (в Telegram уже есть реферальная система в `start.py` — донастроить награды)
- Email-рассылки через Unisender для ретеншна
- Сегментация пользователей по запросам (данные из `quiz_answers`)
- Premium-отчёты и персональные консультации
- Интеграция с аналитикой (Amplitude, Mixpanel)

---

## 📋 Чек-лист завершения Фазы 3

- [x] VK-приложение зарегистрировано (ID: 54660807)
- [x] Креды прописаны в `.env` (`VK_CLIENT_SECRET`, `VK_SERVICE_TOKEN`)
- [x] `vk_auth` в `AuthService` реализован
- [x] Эндпоинт `/api/v1/auth/vk` принимает `access_token` + `user_id`
- [x] Кнопка VK ID One Tap в `mini.html`
- [x] Rate limit для `/api/v1/auth/vk` (10/minute)
- [ ] Протестирован flow на staging
- [ ] Настроен мониторинг Sentry
- [ ] ~~A/B тест Email vs SMS~~ (отменено — SMS удалён)

---

##  Статус на текущий момент

| Компонент | Статус |
|-----------|--------|
| Guest profile (создание+кэш) | ✅ |
| Email magic link (send+verify) | ✅ (без ключа Unisender — письма не отправляются) |
| ~~SMS code (send+verify)~~ | ❌ Удалён из кода |
| Merge guest → user | ✅ |
| Telegram deep link (генерация) | ✅ |
| VK ID (One Tap) | ✅ Код + ключи готовы |
| Celery cleanup beat | ✅ |
| ~~Unisender API~~ | ✅ Заменён на Beget SMTP (`e2c4b32`) |
| ~~SMS.ru API~~ | ❌ Не требуется |
| Миграция на VPS | ✅ `c4d5e6f7a8b9` на head |
| Email transport | ✅ Beget SMTP (развёрнуто и проверено 01.07.2026) |
| SMTP_PASSWORD | ✅ прописан в .env |
