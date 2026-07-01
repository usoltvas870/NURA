# План реализации авторизации и ретеншна для NURA PWA

**Версия:** 1.0  
**Дата:** Июль 2026  
**Статус:** Готов к реализации  
**Стек:** Python 3.11, FastAPI 0.115, aiogram 3.13, SQLAlchemy 2.0, Redis 7, Celery

---

## 📋 Содержание

1. [Архитектура данных](#1-архитектура-данных)
2. [API Endpoints](#2-api-endpoints)
3. [Celery Tasks](#3-celery-tasks)
4. [Redis Keys](#4-redis-keys)
5. [Frontend изменения](#5-frontend-изменения)
6. [Telegram-бот](#6-telegram-бот)
7. [Миграции](#7-миграции)
8. [Тесты](#8-тесты)
9. [Roadmap](#9-roadmap)

---

## 1. Архитектура данных

### 1.1. Модели SQLAlchemy

**Файл:** `core/models.py`

#### Расширение модели User

```python
class User(Base):
    __tablename__ = "users"
    
    # Существующие поля
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    
    # НОВЫЕ ПОЛЯ
    email: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    auth_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'email', 'sms', 'vk', 'telegram'
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Guest profile данные (JSONB)
    guest_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    guest_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guest_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

#### Новая модель GuestProfile (опционально, если не используем guest_data в User)

```python
class GuestProfile(Base):
    __tablename__ = "guest_profiles"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guest_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quiz_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    merged_to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
```

### 1.2. Pydantic Schemas

**Файл:** `core/schemas/auth.py`

```python
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class GuestProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    birth_date: str = Field(..., pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    quiz_answers: dict | None = None

class GuestProfileResponse(BaseModel):
    guest_token: str
    expires_at: datetime

class EmailAuthRequest(BaseModel):
    email: EmailStr
    guest_token: str | None = None

class EmailAuthResponse(BaseModel):
    message: str
    expires_in: int  # seconds

class SMSAuthRequest(BaseModel):
    phone: str = Field(..., pattern=r"^\+7\d{10}$")
    guest_token: str | None = None

class SMSAuthResponse(BaseModel):
    message: str
    expires_in: int

class SMSVerifyRequest(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=6)
    guest_token: str | None = None

class VKAuthRequest(BaseModel):
    code: str  # authorization code from VK
    guest_token: str | None = None

class MergeGuestRequest(BaseModel):
    guest_token: str

class MergeGuestResponse(BaseModel):
    success: bool
    user_id: str
```

---

## 2. API Endpoints

**Файл:** `api/routes/auth.py` (новый файл)

### 2.1. Guest Profile

```python
POST /api/v1/auth/guest
```

**Логика:**
1. Генерируем `guest_token = uuid.uuid4().hex`
2. Создаём запись в `guest_profiles` (или в `users` с `guest_data`)
3. Сохраняем в Redis: `guest_profile:{guest_token}` → profile_data (TTL 30 дней)
4. Возвращаем `guest_token` и `expires_at`

**Rate limit:** `10/minute` per IP

---

### 2.2. Email Magic Link

```python
POST /api/v1/auth/email/send
```

**Логика:**
1. Валидируем email
2. Генерируем `magic_token = uuid.uuid4().hex`
3. Находим или создаём пользователя по email
4. Если есть `guest_token` → привязываем guest данные к пользователю
5. Сохраняем в Redis: `magic_link:{magic_token}` → user_id (TTL 15 минут)
6. Запускаем Celery task: `send_magic_link_email.delay(email, magic_token)`
7. Возвращаем `message: "Письмо отправлено"`, `expires_in: 900`

**Rate limit:** `3/minute` per email

---

```python
GET /api/v1/auth/email/verify?token={magic_token}
```

**Логика:**
1. Получаем `user_id` из Redis по `magic_link:{token}`
2. Если не найден → 400 "Токен истёк"
3. Обновляем пользователя: `email_verified = True`, `auth_method = 'email'`
4. Удаляем токен из Redis
5. Устанавливаем сессию: `set_session_cookie(response, session_id)`
6. Возвращаем `{success: true, user_id: str}`

---

### 2.3. SMS Code

```python
POST /api/v1/auth/sms/send
```

**Логика:**
1. Валидируем phone (формат `+7XXXXXXXXXX`)
2. Генерируем `code = random.randint(1000, 9999)` (4 цифры)
3. Находим или создаём пользователя по phone
4. Если есть `guest_token` → привязываем guest данные
5. Сохраняем в Redis: `sms_code:{phone}` → code (TTL 5 минут)
6. Запускаем Celery task: `send_sms_code.delay(phone, code)`
7. Возвращаем `message: "Код отправлен"`, `expires_in: 300`

**Rate limit:** `3/minute` per phone, `10/hour` per IP

---

```python
POST /api/v1/auth/sms/verify
```

**Логика:**
1. Получаем `code` из Redis по `sms_code:{phone}`
2. Сравниваем с введённым кодом
3. Если не совпадает → 400 "Неверный код"
4. Обновляем пользователя: `phone_verified = True`, `auth_method = 'sms'`
5. Удаляем код из Redis
6. Устанавливаем сессию
7. Возвращаем `{success: true, user_id: str}`

---

### 2.4. VK ID (опционально, Фаза 3)

```python
POST /api/v1/auth/vk
```

**Логика:**
1. Получаем `code` из VK OAuth
2. Обмениваем code на access_token через VK API
3. Получаем user info (id, first_name, last_name, email)
4. Находим или создаём пользователя по `vk_id` (нужно добавить поле `vk_id` в User)
5. Если есть `guest_token` → merge
6. Устанавливаем сессию
7. Возвращаем `{success: true, user_id: str}`

**Rate limit:** `10/minute` per IP

---

### 2.5. Merge Guest → User

```python
POST /api/v1/auth/merge
```

**Логика:**
1. Получаем `guest_token` из запроса
2. Получаем `user_id` из текущей сессии (авторизованный пользователь)
3. Загружаем guest данные из Redis или БД
4. Обновляем пользователя: `name = guest.name`, `birth_date = guest.birth_date`, `guest_data = guest.quiz_answers`
5. Создаём отчёт для пользователя (если есть `guest.report_data`)
6. Помечаем guest profile как merged: `merged_to_user_id = user.id`
7. Удаляем guest данные из Redis
8. Возвращаем `{success: true, user_id: str}`

---

## 3. Celery Tasks

**Файл:** `core/tasks/auth.py` (новый файл)

### 3.1. Отправка Magic Link

```python
@celery_app.task(bind=True, max_retries=3)
def send_magic_link_email(self, email: str, token: str):
    """Отправляет email с magic link"""
    link = f"https://nura-ai.ru/auth/verify?token={token}"
    
    # Используем Unisender API
    try:
        response = httpx.post(
            "https://api.unisender.com/ru/api/sendEmail",
            data={
                "api_key": settings.unisender_api_key,
                "sender_email": "noreply@nura-ai.ru",
                "sender_name": "Нура",
                "recipient": email,
                "subject": "Ваш персональный отчёт готов ✨",
                "body": f"""
                <h2>Ваш отчёт готов!</h2>
                <p>Нажмите на ссылку, чтобы получить доступ:</p>
                <a href="{link}">Получить отчёт</a>
                <p>Ссылка действительна 15 минут.</p>
                """
            }
        )
        response.raise_for_status()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

### 3.2. Отправка SMS

```python
@celery_app.task(bind=True, max_retries=3)
def send_sms_code(self, phone: str, code: str):
    """Отправляет SMS с кодом"""
    message = f"Ваш код для Нура: {code}. Действителен 5 минут."
    
    # Используем SMS.ru API
    try:
        response = httpx.get(
            "https://sms.ru/sms/send",
            params={
                "api_id": settings.sms_ru_api_id,
                "to": phone,
                "msg": message,
                "json": 1
            }
        )
        data = response.json()
        if data["status"] != "OK":
            raise Exception(f"SMS send failed: {data}")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

### 3.3. Очистка expired guest profiles

```python
@celery_app.task
def cleanup_expired_guest_profiles():
    """Удаляет expired guest profiles из БД"""
    # Запускается раз в день через Celery Beat
    async def _cleanup():
        async with get_async_sessionmaker()() as session:
            await session.execute(
                delete(GuestProfile).where(GuestProfile.expires_at < datetime.now(timezone.utc))
            )
            await session.commit()
    
    asyncio.run(_cleanup())
```

---

## 4. Redis Keys

| Key Pattern | Value | TTL | Назначение |
|-------------|-------|-----|-----------|
| `guest_profile:{token}` | JSON profile data | 30 дней | Guest profile данные |
| `magic_link:{token}` | user_id (UUID) | 15 минут | Magic link token |
| `sms_code:{phone}` | code (4 цифры) | 5 минут | SMS verification code |
| `tg_link:{token}` | user_id (UUID) | 15 минут | Telegram deep link token |
| `rate_limit:auth:{ip}` | counter | 1 минута | Rate limiting |

---

## 5. Frontend изменения

### 5.1. mini.html (лендинг с квизом)

**Изменения:**

1. После получения мини-отчёта показать экран авторизации:

```html
<div id="auth-screen" style="display: none;">
  <h2>🌙 Ваш персональный отчёт готов</h2>
  <p>Куда его отправить?</p>
  
  <button id="btn-email" class="btn-primary">
    📧 Получить на Email
  </button>
  <small>Magic Link, без пароля</small>
  
  <button id="btn-sms" class="btn-secondary">
    📱 Получить по SMS
  </button>
  <small>Код придёт в сообщении</small>
  
  <a href="#" id="btn-vk" style="display: none;">
    🔵 Войти через ВКонтакте
  </a>
</div>
```

2. JavaScript логика:

```javascript
// После получения отчёта
document.getElementById('btn-email').addEventListener('click', async () => {
  const email = prompt('Введите ваш email:');
  if (!email) return;
  
  const response = await fetch('/api/v1/auth/email/send', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      email: email,
      guest_token: localStorage.getItem('guest_token')
    })
  });
  
  if (response.ok) {
    showSuccess('Письмо отправлено! Проверьте почту.');
  }
});

// Аналогично для SMS
```

3. Сохранение guest profile:

```javascript
// При начале квиза
async function startQuiz() {
  const response = await fetch('/api/v1/auth/guest', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      name: document.getElementById('name').value,
      birth_date: document.getElementById('birth_date').value
    })
  });
  
  const data = await response.json();
  localStorage.setItem('guest_token', data.guest_token);
}
```

### 5.2. PWA (app/index.html)

**Изменения:**

1. Проверка авторизации:

```javascript
// При загрузке PWA
async function checkAuth() {
  const response = await fetch('/api/v1/web/session-check', {
    credentials: 'same-origin'
  });
  
  if (!response.ok) {
    location.href = '/mini.html';  // Редирект на лендинг
  }
}
```

2. Если пользователь вернулся с guest profile:

```javascript
async function restoreGuestProfile() {
  const guestToken = localStorage.getItem('guest_token');
  if (!guestToken) return;
  
  const response = await fetch(`/api/v1/auth/guest/${guestToken}`);
  if (response.ok) {
    const data = await response.json();
    showRestorePrompt(data);  // "Вы остановились на шаге X. Продолжить?"
  }
}
```

---

## 6. Telegram-бот

**Файл:** `bot/handlers/auth.py` (новый файл)

### 6.1. Deep Link Handler

```python
@router.message(CommandStart())
async def cmd_start(message: Message, command: Command):
    """Обрабатывает /start с параметрами"""
    args = command.args
    
    if args and args.startswith("link_"):
        # Связывание Telegram ID с Email
        token = args[5:]  # Убираем "link_"
        redis = get_redis()
        user_id = await redis.get(f"tg_link:{token}")
        
        if user_id:
            # Привязываем telegram_id к пользователю
            user_repo = UserRepository(get_async_sessionmaker())
            await user_repo.update_telegram_id(uuid.UUID(user_id), message.from_user.id)
            
            await message.answer(
                "✅ Отлично! Теперь вы получите доступ к закрытому каналу с ежедневными прогнозами."
            )
            
            # Отправляем PDF-отчёт (если есть)
            # ...
        else:
            await message.answer("Ссылка истекла. Пожалуйста, запросите новую.")
    else:
        # Обычный /start
        await message.answer("Привет! Я бот Нура. 🌙")
```

### 6.2. Генерация Deep Link

**Файл:** `api/routes/auth.py`

```python
@router.post("/generate-tg-link")
async def generate_telegram_link(user: User = Depends(get_current_web_user)):
    """Генерирует deep link для связывания с Telegram"""
    token = uuid.uuid4().hex
    redis = get_redis()
    await redis.setex(f"tg_link:{token}", 900, str(user.id))  # TTL 15 минут
    
    bot_username = settings.bot_username
    return {
        "tg_url": f"https://t.me/{bot_username}?start=link_{token}",
        "expires_in": 900
    }
```

---

## 7. Миграции

**Файл:** `alembic/versions/xxxx_add_auth_fields.py`

```python
def upgrade() -> None:
    # Добавляем поля в users
    op.add_column("users", sa.Column("email", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("auth_method", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("phone_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("guest_data", postgresql.JSONB(), nullable=True))
    op.add_column("users", sa.Column("guest_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("guest_expires_at", sa.DateTime(timezone=True), nullable=True))
    
    # Добавляем unique constraints
    op.create_unique_constraint("uq_user_email", "users", ["email"])
    op.create_unique_constraint("uq_user_phone", "users", ["phone"])
    
    # Создаём таблицу guest_profiles (опционально)
    op.create_table(
        "guest_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guest_token", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("birth_date", sa.String(10), nullable=True),
        sa.Column("quiz_answers", postgresql.JSONB(), nullable=True),
        sa.Column("report_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("merged_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_guest_profiles_guest_token", "guest_profiles", ["guest_token"])
    op.create_index("ix_guest_profiles_expires_at", "guest_profiles", ["expires_at"])


def downgrade() -> None:
    op.drop_table("guest_profiles")
    op.drop_constraint("uq_user_phone", "users", type_="unique")
    op.drop_constraint("uq_user_email", "users", type_="unique")
    op.drop_column("users", "guest_expires_at")
    op.drop_column("users", "guest_created_at")
    op.drop_column("users", "guest_data")
    op.drop_column("users", "phone_verified")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "auth_method")
    op.drop_column("users", "phone")
    op.drop_column("users", "email")
```

---

## 8. Тесты

**Файл:** `tests/test_auth.py`

### 8.1. Unit-тесты

```python
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_create_guest_profile(client: AsyncClient):
    response = await client.post("/api/v1/auth/guest", json={
        "name": "Алина",
        "birth_date": "15.03.1990"
    })
    assert response.status_code == 200
    data = response.json()
    assert "guest_token" in data
    assert "expires_at" in data

@pytest.mark.asyncio
async def test_send_magic_link(client: AsyncClient, mock_celery):
    response = await client.post("/api/v1/auth/email/send", json={
        "email": "test@example.com"
    })
    assert response.status_code == 200
    assert "expires_in" in response.json()
    mock_celery.send_magic_link_email.delay.assert_called_once()

@pytest.mark.asyncio
async def test_verify_magic_link(client: AsyncClient, redis):
    # Создаём токен в Redis
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    await redis.setex(f"magic_link:test_token", 900, user_id)
    
    response = await client.get("/api/v1/auth/email/verify?token=test_token")
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # Токен должен быть удалён
    token = await redis.get("magic_link:test_token")
    assert token is None

@pytest.mark.asyncio
async def test_send_sms_code(client: AsyncClient, mock_celery):
    response = await client.post("/api/v1/auth/sms/send", json={
        "phone": "+79991234567"
    })
    assert response.status_code == 200
    mock_celery.send_sms_code.delay.assert_called_once()

@pytest.mark.asyncio
async def test_verify_sms_code(client: AsyncClient, redis):
    # Сохраняем код в Redis
    await redis.setex("sms_code:+79991234567", 300, "1234")
    
    response = await client.post("/api/v1/auth/sms/verify", json={
        "phone": "+79991234567",
        "code": "1234"
    })
    assert response.status_code == 200
    assert response.json()["success"] is True
```

### 8.2. Интеграционные тесты

```python
@pytest.mark.asyncio
async def test_full_auth_flow_email(client: AsyncClient, mock_celery, redis):
    # 1. Создаём guest profile
    guest_response = await client.post("/api/v1/auth/guest", json={
        "name": "Алина",
        "birth_date": "15.03.1990"
    })
    guest_token = guest_response.json()["guest_token"]
    
    # 2. Отправляем magic link
    email_response = await client.post("/api/v1/auth/email/send", json={
        "email": "test@example.com",
        "guest_token": guest_token
    })
    assert email_response.status_code == 200
    
    # 3. Получаем токен из Redis (в реальности пользователь получает его по email)
    magic_token = None
    async for key in redis.scan_iter("magic_link:*"):
        magic_token = key.decode().split(":")[1]
        break
    
    # 4. Верифицируем magic link
    verify_response = await client.get(f"/api/v1/auth/email/verify?token={magic_token}")
    assert verify_response.status_code == 200
    user_id = verify_response.json()["user_id"]
    
    # 5. Проверяем, что guest данные привязались к пользователю
    user_response = await client.get("/api/v1/web/me", cookies=verify_response.cookies)
    assert user_response.status_code == 200
    user_data = user_response.json()
    assert user_data["name"] == "Алина"
    assert user_data["birth_date"] == "15.03.1990"
```

---

## 9. Roadmap

### Фаза 1: MVP (2 недели)

**Неделя 1:**
- [ ] Создать модели `User` (расширение) и `GuestProfile`
- [ ] Написать миграцию Alembic
- [ ] Реализовать endpoint `POST /api/v1/auth/guest`
- [ ] Реализовать endpoint `POST /api/v1/auth/email/send`
- [ ] Реализовать endpoint `GET /api/v1/auth/email/verify`
- [ ] Написать Celery task `send_magic_link_email`
- [ ] Настроить Unisender SMTP

**Неделя 2:**
- [ ] Обновить `mini.html`: добавить экран авторизации после отчёта
- [ ] Добавить JavaScript для guest profile и email auth
- [ ] Написать тесты для auth endpoints
- [ ] Протестировать flow на staging

**Результат фазы 1:** Пользователь может получить мини-отчёт анонимно, затем авторизоваться через email и получить полный доступ к PWA.

---

### Фаза 2: SMS + Telegram (1 месяц)

- [ ] Реализовать endpoint `POST /api/v1/auth/sms/send`
- [ ] Реализовать endpoint `POST /api/v1/auth/sms/verify`
- [ ] Написать Celery task `send_sms_code`
- [ ] Настроить SMS.ru API
- [ ] Добавить SMS как backup метод в `mini.html`
- [ ] Реализовать Telegram deep link handler в боте
- [ ] Добавить endpoint `POST /api/v1/auth/generate-tg-link`
- [ ] Обновить PWA: добавить кнопку "Перейти в Telegram"
- [ ] Настроить Celery Beat для `cleanup_expired_guest_profiles`

**Результат фазы 2:** Пользователь может авторизоваться через SMS. После авторизации может перейти в Telegram-бот для получения бонуса.

---

### Фаза 3: VK ID + Оптимизация (2-3 месяц)

- [ ] Зарегистрировать VK приложение, получить client_id/secret
- [ ] Реализовать endpoint `POST /api/v1/auth/vk`
- [ ] Добавить VK ID как опцию в `mini.html` (показывать если реферер = vk.com)
- [ ] A/B тест: Email-first vs SMS-first
- [ ] Оптимизация конверсии (аналитика, heatmaps)
- [ ] Добавить rate limiting для auth endpoints
- [ ] Настроить мониторинг (Sentry, Prometheus)

**Результат фазы 3:** Полноценная система авторизации с несколькими методами. Оптимизированная конверсия.

---

### Фаза 4: Масштабирование (4+ месяц)

- [ ] Реферальная программа через Telegram-бот
- [ ] Email-рассылки (Unisender) для ретеншна
- [ ] Сегментация пользователей по запросам
- [ ] Premium-отчёты и персональные консультации
- [ ] Предупреждение о VPN на чекауте
- [ ] Интеграция с аналитикой (Amplitude, Mixpanel)

---

## 10. Конфигурация

**Файл:** `core/config.py`

```python
class Settings(BaseSettings):
    # Существующие поля
    # ...
    
    # НОВЫЕ ПОЛЯ
    unisender_api_key: str = ""
    sms_ru_api_id: str = ""
    vk_client_id: str = ""
    vk_client_secret: str = ""
    
    guest_profile_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15
    sms_code_ttl_minutes: int = 5
```

**Файл:** `.env`

```env
UNISENDER_API_KEY=your_api_key_here
SMS_RU_API_ID=your_api_id_here
VK_CLIENT_ID=your_vk_client_id
VK_CLIENT_SECRET=your_vk_client_secret
```

---

## 11. Чек-лист готовности

### Техническая готовность:
- [ ] Модели созданы и мигрированы
- [ ] Endpoints работают и протестированы
- [ ] Celery tasks выполняются
- [ ] Redis keys настроены
- [ ] Frontend обновлён
- [ ] Telegram-бот обрабатывает deep links
- [ ] Тесты написаны и проходят

### Юридическая готовность:
- [ ] Галочка "Согласие на обработку ПДн" на всех формах
- [ ] Политика конфиденциальности обновлена
- [ ] Используются только РФ-сервисы (Unisender, SMS.ru)
- [ ] Нет Google ID / Apple ID

### UX-готовность:
- [ ] Все тексты в тоне "заботливая подруга"
- [ ] Нет слова "Регистрация" до Value Moment
- [ ] Обработка ошибок (не пришло письмо, не пришла SMS)
- [ ] Rate limiting настроен

---

## 12. Метрики успеха

| Метрика | Целевое значение | Как измерять |
|---------|------------------|--------------|
| Квиз → Тизер | >85% | Аналитика событий |
| Тизер → Auth (Email/SMS) | >40% | Конверсия leadwall |
| Auth → TG-бот | >25% | Подписки на бота |
| Drop на VPN-переключениях | <10% | Session replay |
| CAC (стоимость регистрации) | <50₽ | Unit-экономика |
| Email vs SMS | 70% / 30% | A/B тесты |

---

## 13. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Email попадает в спам | Высокая | Среднее | Настроить SPF/DKIM/DMARC, использовать проверенный ESP |
| SMS не доходит | Средняя | Высокое | Использовать надёжного провайдера (SMS.ru), добавить retry |
| Пользователь не переходит в TG | Высокая | Среднее | Упростить flow, добавить напоминание через email |
| VPN блокирует оплату | Высокая | Высокое | Предупреждение на чекауте, альтернативные методы оплаты |
| Rate limit слишком строгий | Средняя | Среднее | Мониторинг, ajuste лимитов |

---

## 14. Следующие шаги

1. **Согласовать план** с командой
2. **Создать ветку** `feature/auth-system`
3. **Начать с Фазы 1** (MVP): guest profile + email auth
4. **Ежедневные стендапы** для трекинга прогресса
5. **Ретро после Фазы 1** для корректировки плана

---

**Версия документа:** 1.0  
**Следующий пересмотр:** После Фазы 1 (через 2 недели)  
**Владелец:** Backend Team  
**Согласовано:** Product, DevOps, UX/UI
