# Auth System — оставшиеся задачи

**Версия:** 1.0  
**Дата:** 02.07.2026  
**Откуда:** реализация `docs/auth_system_implementation_plan.md` (Фазы 1+2 завершены, 3 частично)

---

## 🔴 Срочно (до деплоя)

### 1. Применить миграцию на VPS

```bash
ssh nura-vps 'cd /opt/nura/nura_app && alembic upgrade head'
```

Миграция `c4d5e6f7a8b9_add_auth_and_guest.py`:
- Добавляет колонки `phone`, `auth_method`, `email_verified`, `phone_verified`, `vk_id` в `users`
- Создаёт partial unique indexes (`uq_user_email_notnull`, `uq_user_phone_notnull`, `uq_user_vk_id_notnull`)
- Создаёт таблицу `guest_profiles`

**Риски:** если в `users.email` есть дубли — partial index пройдёт (ограничение только на NOT NULL).

### 2. Прописать API-ключи в `.env` на VPS

Добавить в `/opt/nura/nura_app/.env`:

```env
UNISENDER_API_KEY=your_unisender_key
SMS_RU_API_ID=your_sms_ru_id
VK_CLIENT_ID=your_vk_client_id
VK_CLIENT_SECRET=your_vk_client_secret
```

Без `UNISENDER_API_KEY` и `SMS_RU_API_ID` задачи Celery логируют warning и не отправляют письма/SMS (не падают с retry).

### 3. Настроить Unisender

- Зарегистрировать/подтвердить отправителя `noreply@nura-ai.ru`
- Настроить SPF/DKIM/DMARC для домена `nura-ai.ru`
- Тема письма: «Ваш персональный отчёт готов» (без эмодзи)

### 4. Настроить SMS.ru

- Зарегистрироваться на sms.ru
- Пополнить баланс
- Убедиться, что отправитель (подпись) соответствует требованиям

---

## 🟡 Фаза 3 — VK ID (реализовано, ждёт ключи)

**Статус:** Код готов, нужно только прописать ключи в `.env`

### Что сделано:
- ✅ Создан метод `vk_auth` в `AuthService` (obmen access_token на user info через `id.vk.ru/oauth2/user_info`)
- ✅ Эндпоинт `POST /api/v1/auth/vk` принимает `{access_token, user_id, guest_token?}` → создаёт/находит пользователя по `vk_id`, устанавливает сессию
- ✅ Добавлен виджет VK ID One Tap в `mini.html` (секция `#stage-auth`)
- ✅ Схема `VKTokenRequest` для валидации запроса
- ✅ Тесты проходят (19/19)

### Что осталось сделать:
1. **Прописать ключи в `.env` на сервере:**
   ```env
   VK_CLIENT_ID=54660807
   VK_CLIENT_SECRET=<защищённый ключ из кабинета VK ID>
   VK_SERVICE_TOKEN=<сервисный ключ доступа>
   ```

2. **Проверить redirect URL в кабинете VK ID:**
   - Должен быть: `https://nura-ai.ru/api/v1/auth/vk/callback`
   - Если нет — добавить в настройках приложения

3. **Протестировать flow:**
   - Открыть `mini.html` → пройти квиз → на экране авторизации нажать кнопку VK ID
   - Авторизоваться через VK → должно редиректить в `/app/`
   - Проверить, что пользователь создан в БД с `vk_id` и `auth_method='vk'`

### Архитектура VK ID интеграции:
- **Фронтенд:** VK ID SDK (One Tap кнопка) → получает `code` → обменивает на `access_token` через `VKID.Auth.exchangeCode()` → отправляет на бэкенд
- **Бэкенд:** `POST /api/v1/auth/vk` → вызывает `id.vk.ru/oauth2/user_info` → находит/создаёт пользователя → устанавливает сессию
- **Callback:** `https://nura-ai.ru/api/v1/auth/vk/callback` — используется VK ID SDK для postMessage (не требует отдельной страницы)

---

## 🟢 Улучшения (после деплоя)

### 10. Celery Beat — cron для `cleanup_expired_guest_profiles`

- Запустить `celery -A core.tasks beat --loglevel=info` на VPS (если ещё не запущен)
- Проверить лог: `cleanup-expired-guests` должен запускаться раз в сутки

### 11. Rate limiting — мониторинг

Все эндпоинты `/api/v1/auth/*` уже обёрнуты в slowapi. Через неделю после деплоя:
- Посмотреть логи на предмет 429 ошибок
- Если слишком много — ослабить лимиты в `api/routes/auth.py`
- Если слишком мало — можно закрутить (сейчас лимиты щадящие по плану)

### 12. Мониторинг Sentry

- Убедиться, что ошибки из `AuthService` (логирование через `logger.exception`) попадают в Sentry
- Проверить, что `send_magic_link_email`/`send_sms_code` логируют ошибки при падении Unisender/SMS.ru

### 13. UX — повторная отправка письма/SMS

Сейчас пользователь не может запросить письмо/код повторно, пока не истечёт TTL. Можно добавить кнопку «Отправить ещё раз» с таймером обратного отсчёта (60 секунд) на фронтенде.

### 14. A/B тест Email vs SMS (Фаза 3 план)

Когда оба канала работают — запустить A/B тест: 70% email-first, 30% SMS-first. Измерять конверсию в регистрацию. Если SMS даёт лучше — поменять порядок кнопок.

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
- [ ] Креды прописаны в `.env` (`VK_CLIENT_SECRET`, `VK_SERVICE_TOKEN`)
- [x] `vk_auth` в `AuthService` реализован
- [x] Эндпоинт `/api/v1/auth/vk` принимает `access_token` + `user_id`
- [x] Кнопка VK ID One Tap в `mini.html`
- [x] Rate limit для `/api/v1/auth/vk` (10/minute)
- [ ] Протестирован flow на staging
- [ ] Настроен мониторинг Sentry
- [ ] A/B тест Email vs SMS

---

##  Статус на текущий момент

| Компонент | Статус |
|-----------|--------|
| Guest profile (создание+кэш) | ✅ |
| Email magic link (send+verify) | ✅ |
| SMS code (send+verify) | ✅ |
| Merge guest → user | ✅ |
| Telegram deep link (генерация) | ✅ (переиспользован `link_token`) |
| VK ID (One Tap) | ✅ код готов, ждёт `VK_CLIENT_SECRET` в `.env` |
| Celery cleanup beat | ✅ |
| Unisender API | ⬜ ключ не прописан |
| SMS.ru API | ⬜ ключ не прописан |
| Миграция на VPS | ⬜ `alembic upgrade head` |
| Тесты | ✅ 19 тестов, все проходят |
