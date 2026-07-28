# NURA — TODO: Доделать auth-рефакторинг (после утери части правок)

> **STATUS: LEGACY — ARCHIVED**
>
> Сохранено как исторический PWA/web-auth recovery TODO. Не является действующей спецификацией или автоматическим backlog. Текущий статус: [implementation/current-status.md](../../../implementation/current-status.md).

## Что уже применено и сохранено (НЕ ТРОГАТЬ без нужды)
- `nura_app/api/dependencies.py` — новая cookie-based сессия (`get_current_web_user`, `get_optional_web_user`, `set_session_cookie`, `clear_session_cookie`, `SESSION_COOKIE_NAME`). Читает cookie `nura_session_id`, возвращает **401** при отсутствии/истечении/not-found (не 404), продлевает expبiry через `renew_session_expiry`, обновляет cookie в `response`.
- `nura_app/core/config.py` — добавлено `web_session_ttl_seconds: int = 7776000` (90 дней).
- `nura_app/core/models.py` — добавлены поля `web_session_expires_at` и `pd_consent_at` (DateTime(tz), nullable) в модель `User`.
- `nura_app/core/repositories/user.py` — обновлён импорт (`from datetime import datetime, timedelta, timezone`, `from core.config import settings`); `create_web_user` теперь устанавливает `web_session_expires_at`; добавлены методы `renew_session_expiry`, `set_pd_consent`, `ensure_web_session`.
- `frontend/**` (mini.html, pwa/app/*.html, nura-pwa.js) — адаптированы под cookie: убран `localStorage('nura_session_id')`, добавлено `credentials: 'same-origin'`, добавлены чекбокс согласия на ПД и кнопка «Войти через Telegram» в mini.html, кнопка удаления аккаунта в profile.html, logout дергает `/web/logout`.
- `nura_app/core/schemas/__init__.py` — `UserCreate` удалён (задача 7).
- `requirements.txt` — удалены `passlib[bcrypt]`, `python-jose[cryptography]` (задача 7).

## Что ещё нужно применить (исправить после утери)

### 1. `nura_app/api/routes/web.py`
Текущее состояние: оригинальное (использует `X-Session-Id`, `session_id` в телах, limiter "10/minute", `MiniAnalysisResponse.session_id`). Привести в соответствие с новой cookie-сессией:

- В imports: убрать `Header`, добавить `Response`; импортировать из `api.dependencies` — `SESSION_COOKIE_NAME, clear_session_cookie, get_current_web_user, get_optional_web_user, get_selectable_partial_web_user` (если нужен), `set_session_cookie`. Добавить `from datetime import datetime, timedelta, timezone` (требуется для test-subscribe).
- `MiniAnalysisRequest`: добавить обязательное поле `pd_consent: bool = Field(..., description="Согласие на обработку ПД")`.
- `MiniAnalysisResponse`: убрать поле `session_id`.
- `CreatePaymentRequest`: убрать поле `session_id` (используем Depends вместо поиска по body).
- `GenerateLinkTokenRequest`: удалить класс (endpoints используют Depends для текущего user).
- `SubscribeRequest`, `ChatRequest`, `NotificationPrefRequest`, `TestSubscribeRequest`: убрать `session_id` (теперь auth из cookie через Depends).
- `/mini-analysis`: rate limit `3/hour`; проверка `if not body.pd_consent: 400`; вызов `set_pd_consent(user.id)`; `set_session_cookie(response, session_id)`; `return MiniAnalysisResponse(**analysis)` без session_id. Сигнатура: `async def mini_analysis(request: Request, body: MiniAnalysisRequest, response: Response)`.
- `/create-payment`: `user: User = Depends(get_current_web_user)`, убрать поиск `body.session_id`.
- `/subscribe`: `user: User = Depends(get_current_web_user)`, убрать поиск.
- `/chat`: `user: User = Depends(get_current_web_user)`, убрать `session_id` из тела и из проверки.
- `/generate-link-token`: `user: User = Depends(get_current_web_user)`, убрать `GenerateLinkTokenRequest` (или оставить пустым).
- `/notifications` (PATCH и GET): `user: User = Depends(get_current_web_user)`, убрать `session_id` из тела.
- `/test-subscribe`: `user: User = Depends(get_current_web_user)`, убрать body, вернуть `datetime` в импорт (для подсчёта `until_date`).
- Добавить `POST /logout`: `clear_session_cookie(response); return {"ok": True}`.
- Добавить `GET /session-check`: `user: User = Depends(get_current_web_user); return {"authenticated": True}`.
- Добавить `POST /auth/start` (rate 10/hour): генерация `auth_token:{uuid}` в Redis с TTL 300, value="pending"; `return AuthStartResponse(token, tg_url=f"https://t.me/{settings.bot_username}?start=tgauth_{token}")`.
- Добавить `GET /auth/check?token=<token>` (rate 60/minute): Redis `GET auth_token:{token}`; если None → `expired`; если "pending" → `pending`; иначе (web_session_id) → `DEL` ключа, `set_session_cookie(response, web_session_id)`, `status=ok`. Сигнатура содержит `response: Response` и `token: str`.
- Добавить `DELETE /account` (rate 3/hour): `user: User = Depends(get_current_web_user)`; удалить `reports`, `payments`, `referral_rewards` через репозиторийные `delete_by_user_id`; удалить user; `clear_session_cookie(response)`; `return {"ok": True}`.
- Модели: `AuthStartResponse(token: str, tg_url: str)`, `AuthCheckResponse(status: str)`.

### 2. `nura_app/api/routes/tarot_pwa.py`
- В imports убрать неиспользуемые (`get_async_sessionmaker`, `UserRepository` больше не нужны для ручного поиска). Оставить `Depends(get_current_web_user)`.
- `SpreadRequest`: убрать поле `session_id` (только `spread_type` + `question`).
- `/daily-card`: оставить `Depends(get_current_web_user)` — работает с cookie.
- `/spread`: сигнатуру поменять — `user: User = Depends(get_current_web_user)`; убрать ручной поиск `get_by_web_session_id(body.session_id)` (есть `user` из dependency). Возвращает 401 при неавторизованном автоматически.
- Константа `3600` минутных rate limits не менять (уже slowapi).

### 3. `nura_app/api/routes/push.py`
- `PushSubscription` / `PushUnsubscribe`: убрать поле `session_id`, оставить `endpoint`, `keys` (для sub), `telegram_id` (fallback для bot).
- `/subscribe` и `/unsubscribe`: добавить `web_user: User | None = Depends(get_optional_web_user)`. Если web_user не None — берём его; иначе fallback на `body.telegram_id` через `get_by_telegram_id`.
- В `/unsubscribe` убрать ранний `if not body.session_id and not body.telegram_id` - теперь проверяем `if web_user is None and not body.telegram_id: 401`.

### 4. `nura_app/bot/handlers/start.py`
Текущее состояние: оригинальное. Нужно:
- Import: добавить `from core.database import get_async_sessionmaker, get_redis` (включая `get_redis`); импортировать новые тексты (`pd_consent_text`, `pd_consent_declined_text`, `tg_auth_success_text`, `delete_account_warning_text`, `delete_account_cancelled_text`, `delete_account_done_text`). Импортировать `from bot.states.onboarding_state import OnboardingStates`.
- В `cmd_start`: ДО ссылок `link_`/`ref_` добавить проверку `if args and args.startswith("tgauth_"): token = args[7:]; await _handle_tg_auth_token(message, token); return`.
- Под онбордингом výsledekného поиска `/user.birth_date`: если `not user.pd_consent_at` показывать `pd_consent_text()` + `_pd_consent_keyboard()` и `state.set_state(OnboardingStates.waiting_for_pd_consent)`, `return` (не запрашивать сразу дату).
- В `_pd_consent_keyboard()`: InlineKeyboardButton("✅ Согласен","pd_consent_yes") и ("❌ Не согласенсен","pd_consent_no").
- Добавить callback-хендлеры:
  - `pd_consent_yes`: `callback.answer()`, очистка state, `user_repo.get_by_telegram_id`; если user — `set_pd_consent(user.id)`. Затем `state.set_state(OnboardingStates.waiting_for_birth_date)` и отправка `onboarding_greeting_text(...)` + `ask_birth_date_onboarding_text()`.
  - `pd_consent_no`: `callback.answer()`, `state.clear()`, отправить `pd_consent_declined_text()`.
- Команда `/delete_account`: отправить `delete_account_warning_text()` + `_delete_account_keyboard()` (InlineKeyboardButton("Да, удалить всё","delete_account_confirm"), ("Отмена","delete_account_cancel")).
- Callback `delete_account_confirm`: lookup user → `report_repo.delete_by_user_id`, `payment_repo.delete_by_user_id` (каскад), `user_repo.delete(user.id)`; отправить `delete_account_done_text()`.
- Callback `delete_account_cancel`: `delete_account_cancelled_text()`.
- Функция `_handle_tg_auth_token(message, token)`: Redis `GETDEL auth_token:{token}`; если None — ошибка "Ссылка недействительна или истекла"; если value != "pending" — "Токен уже использован"; иначе: найти/создать user по `telegram_id`, сгенерировать `web_session_id = uuid.uuid4().hex`, `user_repo.ensure_web_session(telegram_id, web_session_id)`, `redis.setex(key, 300, web_session_id)` (тот же ключ), отправить `tg_auth_success_text()` + `open_pwa_keyboard()`.

### 5. `nura_app/bot/states/onboarding_state.py`
Добавить `waiting_for_pd_consent = State()` в `OnboardingStates`.

### 6. `nura_app/bot/texts/onboarding.py`
Добавить функции (без эмодзи-перегруза): `pd_consent_text()`, `pd_consent_declined_text()`, `tg_auth_success_text()`, `delete_account_warning_text()`, `delete_account_cancelled_text()`, `delete_account_done_text()`. Тексты — смотри прежний план вверху этой сессии.

### 7. `nura_app/bot/main.py`
Добавить `BotCommand(command="delete_account", description="🗑 Удалить аккаунт")` в список команд.

### 8. `nura_app/core/repositories/report.py`
Добавить метод `delete_by_user_id(user_id)`:
```python
async def delete_by_user_id(self, user_id: uuid.UUID) -> None:
    async with self._session_factory() as session:
        await session.execute(delete(Report).where(Report.user_id == user_id))
        await session.commit()
```
Import: `from sqlalchemy import delete, desc, select` (добавить `delete`).

### 9. `nura_app/core/repositories/payment.py`
Добавить метод `delete_by_user_id(user_id)`, который каскадно удаляет `referral_rewards` (по referrer_id/referred_id) и `payments` (по user_id):
```python
async def delete_by_user_id(self, user_id: uuid.UUID) -> None:
    async with self._session_factory() as session:
        await session.execute(
            delete(ReferralReward).where(
                (ReferralReward.referrer_id == user_id)
                | (ReferralReward.referred_id == user_id)
            )
        )
        await session.execute(
            delete(Payment).where(Payment.user_id == user_id)
        )
        await session.commit()
```
Import: `from core.models import Payment, ReferralReward` и `from sqlalchemy import delete, select`.

### 10. Alembic миграции (две)
- `nura_app/alembic/versions/d4e5f6a7b8c9_add_web_session_expires_at.py`: `revision="d4e5f6a7b8c9"`, `down_revision="c3d4e5f6a7b8"`, добавляет колонку `web_session_expires_at DateTime(timezone=True) nullable`.
- `nura_app/alembic/versions/e5f6a7b8c9d0_add_pd_consent_at.py`: `revision="e5f6a7b8c9d0"`, `down_revision="d4e5f6a7b8c9"`, добавляет колонку `pd_consent_at DateTime(timezone=True) nullable`.

### 11. `nura_app/tests/test_tarot_pwa.py`
- `mock_get_user` fixture: добавить патч `UserRepository.renew_session_expiry` как `AsyncMock(return_value=None)`.
- Все вызовы `GET /daily-card`: `headers={"X-Session-Id": MOCK_SESSION_ID}` → `cookies={"nura_session_id": MOCK_SESSION_ID}`.
- Все вызовы `POST /spread`: убрать `session_id` из JSON тел (из `SPREAD_BODY` и inline-боди), оставить только `spread_type`/`question`; добавить `cookies={"nura_session_id": MOCK_SESSION_ID}`.
- Тесты ожидания ошибок «неавторизован» (отсутствие session, невалидный): 404 → 401.
- `test_session_id_required` и подобные — удалить либо заменить проверкой обязательности `spread_type`.
- Запустить: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_tarot_pwa.py -x -q`. Должно пройти ~95-102 теста.

### 12. Финальные проверки
- `$env:PYTHONIOENCODING="utf-8"; ruff check .`
- `python -m pytest tests/test_tarot_pwa.py -x -q`
- Если есть `tests/test_web*.py` — поправить аналогично (cookies + 401 + без session_id в телах).
- Миграция: ни в коем случае не запускать `alembic upgrade head` локально без БД — только autogenerate/test на CI.

## Важные проверочные шаги
- Текущее состояние каждого правимого файла проверяй через `grep` (например, `grep web_session_expires_at nura_app/core/models.py`) перед началом, чтобы не применить правки второй раз.
- После пакетной правки запускай `git diff --stat` и убеждайся, что все файлы помечены изменёнными.

## Источник истины по фронтенду
Фронтенд уже сохранён и не требует переделки — просто читай текущее состояние frontend через read.
