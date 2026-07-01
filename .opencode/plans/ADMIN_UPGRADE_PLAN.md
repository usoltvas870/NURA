# ADMIN_UPGRADE_PLAN.md — Промт для агента-оркестратора

> Ты — агент-оркестратор. Получи этот промт, загрузи контекст проекта (прочитай ADMIN_UPGRADE_PLAN.md и ключевые файлы), и выполни ВСЕ 4 фазы доработки админ-панели в рамках одной сессии через запуск субагентов.

---

## Твоя роль

Ты НЕ пишешь код сам. Ты:
1. Читаешь текущее состояние файлов (подтягиваешь контекст)
2. Запускаешь субагентов с чёткими промтами на конкретные изменения
3. Ждёшь результаты, валидируешь их
4. Разруливаешь конфликты (два субагента не должны трогать один файл одновременно)
5. В конце запускаешь `ruff check .` и `pytest` из `nura_app/`

---

## Ограничения параллельности

Два субагента **не могут** одновременно редактировать один и тот же файл. Если файл общий — запускай субагентов последовательно.

**Карта общих файлов:**

| Файл | Затрагивают фазы |
|------|-----------------|
| `api/routes/admin_api.py` | 1, 2, 3, 4 |
| `frontend/admin/index.html` | 1, 2, 3, 4 |
| `core/models.py` | 2 |
| `core/repositories/user.py` | 1 |
| `api/routes/web.py` | 2 |
| `frontend/pwa/app/profile.html` | 2 |

---

## План запуска субагентов (порядок)

### Шаг 0 — Загрузка контекста (ты сам)

Прочитай эти файлы чтобы передать актуальный код в промты субагентам:
- `nura_app/api/routes/admin_api.py`
- `nura_app/core/repositories/user.py`
- `nura_app/core/models.py`
- `nura_app/frontend/admin/index.html`
- `nura_app/api/routes/web.py`
- `nura_app/frontend/pwa/app/profile.html` (секция оплаты подписки)

### Шаг 1 — Параллельный запуск: Бэкенд Фазы 1 + Модель Фазы 2

Эти два субагента работают с **разными файлами** — можно параллельно.

#### Субагент 1A: Бэкенд Фазы 1 — Действия над пользователем

```
Тип: Backend Architect
Файлы: nura_app/api/routes/admin_api.py, nura_app/core/repositories/user.py

Задача: добавить 6 эндпоинтов в admin_api.py и 3 метода в user.py.

### В api/routes/admin_api.py добавить (после существующих эндпоинтов, перед broadcast):

Схемы (новые Pydantic модели):

class UserDetailReport(BaseModel):
    report_type: str
    token: str
    url: str
    created_at: str

class UserDetailPayment(BaseModel):
    amount: int
    status: str
    payment_type: str
    created_at: str

class UserDetailResponse(BaseModel):
    id: str
    telegram_id: int | None
    username: str | None
    first_name: str | None
    name: str | None
    birth_date: str | None
    main_archetype: str | None
    main_archetype_number: int | None
    subscription_status: str
    subscription_until: str | None
    tarot_subscription: bool
    tarot_subscription_until: str | None
    has_matrix: bool
    has_pwa_push: bool
    web_session_expires_at: str | None
    created_at: str
    reports: list[UserDetailReport]
    payments: list[UserDetailPayment]

class ExtendSubscriptionRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650)

class GrantSubscriptionRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650)

Эндпоинты (все под существующим prefix="/api/v1/admin"):

1. GET /users/{user_id} → UserDetailResponse
   - Найти юзера по UUID user_id
   - Вернуть все поля + reports (из таблицы reports, отсортированные по created_at desc) + payments (последние 10, отсортированные по created_at desc)
   - web_session_expires_at в isoformat
   - Если юзер не найден → 404

2. POST /users/{user_id}/subscription/extend → {"ok": True, "subscription_until": "..."}
   - Тело: ExtendSubscriptionRequest
   - Если subscription_until есть: добавить days к нему
   - Если subscription_until нет: установить now + days
   - Если subscription_status != "premium": установить "premium"
   - Вернуть новое subscription_until в isoformat

3. POST /users/{user_id}/tarot/extend → {"ok": True, "tarot_subscription_until": "..."}
   - Аналогично для tarot_subscription_until
   - Установить tarot_subscription = True
   - Если tarot_subscription_until есть: добавить days
   - Если нет: установить now + days

4. POST /users/{user_id}/subscription/grant → {"ok": True, "subscription_until": "..."}
   - Тело: GrantSubscriptionRequest
   - Установить subscription_status = "premium"
   - subscription_until = now + days

5. POST /users/{user_id}/tarot/grant → {"ok": True, "tarot_subscription_until": "..."}
   - tarot_subscription = True
   - tarot_subscription_until = now + days

6. POST /users/{user_id}/regenerate-matrix → {"ok": True}
   - Проверить что у юзера есть birth_date (иначе 400: "Нет даты рождения")
   - Найти существующий полный отчёт (report_type="full") — если есть, удалить его
   - Запустить generate_full_report(user_id, report_token=новый_токен)
   - Импорт: from core.tasks import generate_full_report; from core.services.report import ReportService

### В core/repositories/user.py добавить методы:

async def extend_subscription(self, user_id: uuid.UUID, days: int) -> User | None:
    - Найти юзера, добавить days к subscription_until (или от now если null), поставить status="premium" если был "free"

async def extend_tarot(self, user_id: uuid.UUID, days: int) -> User | None:
    - Найти юзера, tarot_subscription=True, добавить days к tarot_subscription_until

async def grant_premium(self, user_id: uuid.UUID, days: int) -> User | None:
    - status="premium", subscription_until=now+days

async def grant_tarot(self, user_id: uuid.UUID, days: int) -> User | None:
    - tarot_subscription=True, tarot_subscription_until=now+days

Правила:
- НИКАКИХ комментариев
- Сохранять стиль: async/await, Pydantic v2, Field validators если нужны
- Использовать get_async_sessionmaker() для сессий
- UUID юзера парсить через uuid.UUID(user_id)
- Все эндпоинты под защитой verify_admin_token (уже на роутере)
- После правок выполнить ruff check nura_app/api/routes/admin_api.py nura_app/core/repositories/user.py
- Вернуть список изменённых файлов
```

#### Субагент 1B: Модель и миграция Фазы 2 — PromoCode

```
Тип: Backend Architect
Файлы: nura_app/core/models.py, nura_app/alembic/versions/

Задача: создать модель PromoCode и alembic миграцию.

### В core/models.py добавить модель (после класса ReferralReward, перед __table_args__ или в конце файла):

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

Импорты: Boolean уже импортирован из sqlalchemy — проверить. UUID/as_uuid уже есть в models.py.

### Создать alembic миграцию:

Выполнить из nura_app/:
alembic revision --autogenerate -m "add_promo_codes"

Проверить что миграция создалась корректно (только таблица promo_codes).

Правила:
- НИКАКИХ комментариев
- Сохранять стиль существующих моделей
- После правок: ruff check nura_app/core/models.py
- Вернуть список созданных/изменённых файлов
```

### Шаг 2 — Жди завершения Шага 1, затем параллельно: Фронтенд Фазы 1 + API Фазы 2

#### Субагент 2A: Фронтенд Фазы 1 — модальное окно пользователя

```
Тип: Frontend Developer
Файл: nura_app/frontend/admin/index.html

ВНИМАНИЕ: этот файл большой (~1600 строк). Вноси изменения ТОЛЬКО в указанные места, не переписывай весь файл.

Задача: добавить модальное окно с детальной карточкой пользователя и кнопками действий.

### Изменения:

1. В <style> (секция CSS) добавить стили для модального окна:
   - .modal-overlay: position fixed, inset 0, z-index 1000, background rgba(0,0,0,.7), display flex, align-items center, justify-content center, backdrop-filter blur(4px)
   - .modal-card: background var(--bg-card), border-radius var(--r-xl), max-width 640px, width calc(100% - 32px), max-height 85vh, overflow-y auto, padding 28px 24px, position relative
   - .modal-close: position absolute, top 16px, right 16px, width 32px, height 32px, border-radius 50%, border 1px solid rgba(var(--border-light-rgb),.15), background transparent, color var(--text-m), cursor pointer, font-size 16px
   - .modal-title: font-family var(--font-serif), font-size 22px, margin-bottom 20px
   - .modal-section: margin-bottom 18px
   - .modal-section-title: font-size 10px, font-weight 800, text-transform uppercase, letter-spacing .08em, color var(--text-s), margin-bottom 8px
   - .modal-row: display flex, justify-content space-between, padding 6px 0, font-size 13px, border-bottom 1px solid rgba(var(--border-light-rgb),.04)
   - .modal-row-label: color var(--text-s)
   - .modal-row-value: color var(--text), font-weight 600
   - .modal-actions: display grid, grid-template-columns 1fr 1fr, gap 8px, margin-top 20px
   - .modal-action-btn: padding 10px 14px, border-radius var(--r-sm), font-family var(--font-sans), font-size 12px, font-weight 700, cursor pointer, border none, transition all .2s
   - .modal-action-btn.primary: background var(--terra), color #fff
   - .modal-action-btn.primary:hover: background var(--terra-d)
   - .modal-action-btn.secondary: background transparent, border 1px solid rgba(var(--border-light-rgb),.12), color var(--text-m)
   - .modal-action-btn.danger: background transparent, border 1px solid var(--red), color var(--red)
   - .modal-action-btn:disabled: opacity .5, cursor not-allowed
   - .modal-report-link: font-size 12px, color var(--terra), text-decoration underline
   - @media (max-width: 480px): .modal-actions grid-template-columns 1fr

2. В HTML (после </main> перед <script>), добавить заготовку модального окна:
   <div class="modal-overlay" id="userModal" style="display:none">
     <div class="modal-card">
       <button class="modal-close" id="modalClose">&times;</button>
       <div id="modalContent"></div>
     </div>
   </div>

3. В renderUsersTable (JS), добавить onclick на каждую строку:
   Вместо простого html += '<tr>' сделать:
   html += '<tr style="cursor:pointer" onclick="openUserDetail(\'' + u.id + '\')">'
   
   Все остальные td внутри строки остаются без изменений.

4. Добавить JS-функции (в конец секции <script>, перед закрывающим тегом):

   window.openUserDetail = function(userId) {
     var modal = document.getElementById('userModal');
     var content = document.getElementById('modalContent');
     modal.style.display = 'flex';
     content.innerHTML = '<div class="loading"><span class="spinner"></span>Загрузка...</div>';
     
     apiFetch('/users/' + userId).then(function(d) {
       if (!d) { content.innerHTML = '<p style="color:var(--red)">Пользователь не найден</p>'; return; }
       
       var subStatus = d.subscription_status === 'premium' 
         ? '<span class="badge badge-premium">Premium</span>' 
         : '<span class="badge badge-free">Free</span>';
       var tarotStatus = d.tarot_subscription 
         ? '<span class="badge badge-premium">Активна</span>' 
         : '<span class="badge badge-free">Нет</span>';
       var pushStatus = d.has_pwa_push 
         ? '<span class="badge badge-success">Да</span>' 
         : '<span class="badge badge-free">Нет</span>';
       
       var reportsHtml = '';
       if (d.reports && d.reports.length) {
         d.reports.forEach(function(r) {
           reportsHtml += '<div class="modal-row">'
             + '<span class="modal-row-label">' + escapeHtml(r.report_type) + '</span>'
             + '<span><a class="modal-report-link" href="' + r.url + '" target="_blank">открыть</a> · ' + escapeHtml(r.created_at || '') + '</span>'
             + '</div>';
         });
       } else {
         reportsHtml = '<div style="font-size:12px;color:var(--text-s);padding:6px 0">Нет отчётов</div>';
       }
       
       var paymentsHtml = '';
       if (d.payments && d.payments.length) {
         d.payments.forEach(function(p) {
           var pBadge = p.status === 'succeeded' ? '<span class="badge badge-success">ok</span>' : '<span class="badge badge-warn">' + escapeHtml(p.status) + '</span>';
           paymentsHtml += '<div class="modal-row">'
             + '<span class="modal-row-label">' + escapeHtml(p.payment_type) + '</span>'
             + '<span>' + formatRubles(p.amount) + ' ' + pBadge + ' · ' + formatDate(p.created_at) + '</span>'
             + '</div>';
         });
       } else {
         paymentsHtml = '<div style="font-size:12px;color:var(--text-s);padding:6px 0">Нет платежей</div>';
       }
       
       var html = '<h2 class="modal-title">' + escapeHtml(d.name || d.first_name || 'Без имени') + '</h2>';
       
       html += '<div class="modal-section">'
         + '<div class="modal-section-title">Профиль</div>'
         + '<div class="modal-row"><span class="modal-row-label">Telegram</span><span class="modal-row-value">' + escapeHtml(d.username ? '@' + d.username : (d.telegram_id ? 'ID:' + d.telegram_id : '-')) + '</span></div>'
         + '<div class="modal-row"><span class="modal-row-label">Дата рождения</span><span class="modal-row-value">' + escapeHtml(d.birth_date || '-') + '</span></div>'
         + '<div class="modal-row"><span class="modal-row-label">Архетип</span><span class="modal-row-value">' + escapeHtml(d.main_archetype || '-') + (d.main_archetype_number ? ' (' + d.main_archetype_number + ')' : '') + '</span></div>'
         + '</div>';
       
       html += '<div class="modal-section">'
         + '<div class="modal-section-title">Подписки</div>'
         + '<div class="modal-row"><span class="modal-row-label">Premium</span><span>' + subStatus + (d.subscription_until ? ' до ' + formatDate(d.subscription_until) : '') + '</span></div>'
         + '<div class="modal-row"><span class="modal-row-label">Таро</span><span>' + tarotStatus + (d.tarot_subscription_until ? ' до ' + formatDate(d.tarot_subscription_until) : '') + '</span></div>'
         + '<div class="modal-row"><span class="modal-row-label">Push</span><span>' + pushStatus + '</span></div>'
         + '</div>';
       
       html += '<div class="modal-section">'
         + '<div class="modal-section-title">Отчёты</div>'
         + reportsHtml
         + '</div>';
       
       html += '<div class="modal-section">'
         + '<div class="modal-section-title">Платежи</div>'
         + paymentsHtml
         + '</div>';
       
       html += '<div class="modal-actions">'
         + '<button class="modal-action-btn primary" onclick="adminAction(\'' + d.id + '\', \'subscription/extend\', \'Продлить premium на 30 дней?\')">Продлить premium 30д</button>'
         + '<button class="modal-action-btn primary" onclick="adminAction(\'' + d.id + '\', \'tarot/extend\', \'Продлить таро на 30 дней?\')">Продлить таро 30д</button>'
         + '<button class="modal-action-btn secondary" onclick="adminAction(\'' + d.id + '\', \'subscription/grant\', \'Выдать premium на 30 дней?\')">Выдать premium 30д</button>'
         + '<button class="modal-action-btn danger" onclick="adminAction(\'' + d.id + '\', \'regenerate-matrix\', \'Перегенерировать матрицу?\')">Перегенерировать</button>'
         + '</div>';
       
       content.innerHTML = html;
     }).catch(function(err) {
       content.innerHTML = '<p style="color:var(--red)">Ошибка: ' + err.message + '</p>';
     });
   };
   
   window.adminAction = function(userId, path, confirmMsg) {
     if (!confirm(confirmMsg)) return;
     var content = document.getElementById('modalContent');
     var btn = event.target;
     if (btn) btn.disabled = true;
     
     var body = null;
     if (path !== 'regenerate-matrix') {
       body = JSON.stringify({ days: 30 });
     }
     
     var fetchOpts = {
       method: 'POST',
       headers: { 'X-Admin-Token': getToken() }
     };
     if (body) {
       fetchOpts.headers['Content-Type'] = 'application/json';
       fetchOpts.body = body;
     }
     
     fetch(API_BASE + '/users/' + userId + '/' + path, fetchOpts)
       .then(function(r) {
         if (!r.ok) return r.json().then(function(e) { throw new Error(e.detail || 'HTTP ' + r.status); });
         return r.json();
       })
       .then(function(d) {
         openUserDetail(userId);
       })
       .catch(function(err) {
         alert('Ошибка: ' + err.message);
         openUserDetail(userId);
       });
   };

5. Закрытие модального окна:
   document.getElementById('modalClose').addEventListener('click', function() {
     document.getElementById('userModal').style.display = 'none';
   });
   document.getElementById('userModal').addEventListener('click', function(e) {
     if (e.target === this) this.style.display = 'none';
   });

6. Экспортировать getToken как window.getToken если ещё не экспортирована:
   После функции getToken добавить: window.getToken = getToken;
   (Или убедиться что adminAction использует правильный способ получения токена)

Правила:
- НИКАКИХ комментариев
- НИКАКИХ template literals (``) — только конкатенация строк и var
- Не ломай существующую функциональность
- escapeHtml уже есть в коде или используй замену < > & " ' через String.replace
- Вернуть список изменений
```

#### Субагент 2B: API Фазы 2 — PromoCode CRUD + применение

```
Тип: Backend Architect
Файлы: nura_app/api/routes/admin_api.py, nura_app/api/routes/web.py

ВНИМАНИЕ: admin_api.py уже изменён Субагентом 1A. Читай файл заново перед редактированием.

Задача:
1. Добавить CRUD для PromoCode в admin_api.py
2. Добавить применение промокода в web.py (create-payment и subscribe)

### Часть 1: admin_api.py — CRUD промокодов

Схемы:

class PromoCodeCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=64)
    discount_percent: int = Field(..., ge=1, le=100)
    max_uses: int | None = None
    expires_at: str | None = None

class PromoCodeResponse(BaseModel):
    id: str
    code: str
    discount_percent: int
    max_uses: int | None
    used_count: int
    expires_at: str | None
    is_active: bool
    created_at: str
    model_config = {"from_attributes": True}

class PromoCodeListResponse(BaseModel):
    codes: list[PromoCodeResponse]
    total: int

Эндпоинты:

1. GET /promo-codes → PromoCodeListResponse
   - Получить все промокоды, отсортированные по created_at desc
   - Из core.models импортировать PromoCode

2. POST /promo-codes → PromoCodeResponse
   - Создать новый промокод
   - code привести к uppercase
   - expires_at распарсить из ISO строки если передано

3. PATCH /promo-codes/{code_id}/toggle → PromoCodeResponse
   - Переключить is_active

4. DELETE /promo-codes/{code_id} → {"ok": True}
   - Удалить промокод

### Часть 2: web.py — применение промокода

В эндпоинты create-payment и subscribe добавить опциональное поле promo_code в тело запроса.

В CreatePaymentRequest добавить:
    promo_code: str | None = None

В SubscribeResponse не менять, но в теле эндпоинта subscribe принимать promo_code опционально.

Логика применения (общая для обоих эндпоинтов, в виде вспомогательной функции или inline):
- Если promo_code передан:
  1. Найти PromoCode по code (upper case)
  2. Если не найден или is_active=False → HTTPException 400 "Промокод недействителен"
  3. Если expires_at < now → HTTPException 400 "Промокод истёк"
  4. Если max_uses не null и used_count >= max_uses → HTTPException 400 "Промокод исчерпан"
  5. Вычислить скидку: new_amount = price * (100 - discount_percent) / 100
  6. Использовать new_amount при создании платежа в YooKassa
  7. Увеличить used_count на 1

Импорт PromoCode: from core.models import PromoCode
Импорт select: from sqlalchemy import select (если ещё не импортирован)

Правила:
- НИКАКИХ комментариев
- Сохранять стиль
- Использовать get_async_sessionmaker()
- После правок ruff check nura_app/api/routes/admin_api.py nura_app/api/routes/web.py
- Вернуть список изменений
```

### Шаг 3 — Жди Шаг 2, затем последовательно: Фронтенд Фаз 2+3+4

Один субагент делает весь оставшийся фронтенд (admin/index.html уже изменён — читать актуальную версию).

```
Тип: Frontend Developer
Файл: nura_app/frontend/admin/index.html

ВНИМАНИЕ: файл уже изменён предыдущими субагентами. Прочитай его заново.

Задача: добавить в админку три новых таба и один блок в Dashboard.

### 1. Новый таб «Промокоды» (Фаза 2)

В <nav class="tabs"> добавить кнопку (после «Рассылка», перед «Логи»):
<button class="tab-btn" data-tab="promo">Промокоды</button>

Новая секция (после section#section-broadcast, перед section#section-logs):
<section id="section-promo" class="section">
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px">
    <input type="text" class="search-input" id="promoCodeInput" placeholder="Код (напр. WELCOME)" style="width:180px">
    <input type="number" class="search-input" id="promoDiscountInput" placeholder="Скидка %" min="1" max="100" style="width:110px">
    <input type="number" class="search-input" id="promoMaxUsesInput" placeholder="Макс. использований" min="1" style="width:140px">
    <input type="text" class="search-input" id="promoExpiresInput" placeholder="Истекает (ГГГГ-ММ-ДД)" style="width:150px">
    <button class="btn-refresh" id="promoCreateBtn">Создать</button>
  </div>
  <div class="table-wrap" id="promoTableWrap"></div>
</section>

JS функции:
- loadPromos(): GET /promo-codes → рендерит таблицу (код, скидка, использовано/макс, истекает, активен, кнопка toggle, кнопка удалить)
- Создание: POST /promo-codes
- Toggle: PATCH /promo-codes/{id}/toggle
- Удаление: DELETE /promo-codes/{id} с confirm

Добавить в loadTabContent() вызов loadPromos() для tab === 'promo'.

### 2. Новый таб «Рефералы» (Фаза 3)

В <nav class="tabs"> добавить кнопку:
<button class="tab-btn" data-tab="referrals">Рефералы</button>

Новая секция:
<section id="section-referrals" class="section">
  <div id="referralsLoading" class="loading"><span class="spinner"></span>Загрузка...</div>
  <div id="referralsContent" style="display:none">
    <div class="kpi-grid" id="referralKpiGrid"></div>
    <div class="card">
      <div class="card-header">Топ рефереров</div>
      <div class="table-wrap" id="referralTableWrap"></div>
    </div>
  </div>
</section>

JS функция loadReferrals():
- Вызвать apiFetch('/stats') — использовать существующие данные
- Показать KPI: всего рефералов (из referral_rewards COUNT), новых за 7д
- Топ рефереров: нужен новый эндпоинт. Если эндпоинта нет — пока просто KPI из stats.

Альтернатива: добавить referral-статистику в существующий GET /stats и использовать её здесь.

Добавить в loadTabContent() вызов loadReferrals() для tab === 'referrals'.

### 3. Dashboard: добавить реферальные KPI (Фаза 3)

В renderKpi() добавить карточки (после существующих):
{ label: 'Рефералов всего', value: d.referrals_total || 0 },
{ label: 'Рефералов новых за 7д', value: d.referrals_new_7d || 0 }

### 4. Dashboard: добавить воронку (Фаза 4)

Добавить в renderKpi() — в конец:
{ label: 'Mini-анализов', value: (d.reports_by_type && d.reports_by_type.mini) || 0 },
{ label: 'Конверсия в полный', value: totalUsers > 0 && fullCount > 0 ? (fullCount / miniCount * 100).toFixed(1) + '%' : '-' }

Где fullCount и miniCount брать из d.reports_by_type.

Правила:
- НИКАКИХ комментариев
- НИКАКИХ template literals — только конкатенация строк
- escapeHtml для всех пользовательских данных
- Не ломать существующие табы и функциональность
- Вернуть список изменений
```

### Шаг 4 — Финальная валидация (ты сам)

Когда все субагенты завершили:

1. Запусти `ruff check .` из `nura_app/`
2. Запусти `pytest --ignore=tests/test_tarot_handlers.py --ignore=tests/test_handlers.py --ignore=tests/test_tasks.py -x -q` из `nura_app/`
3. Если есть ошибки — почини их сам (мелкие) или перезапусти субагента с указанием ошибки
4. Обнови STATE.md — добавь запись о сессии

---

## Итоговая карта файлов после всех изменений

| Файл | Что изменилось |
|------|---------------|
| `api/routes/admin_api.py` | +6 эндпоинтов действий над юзером + CRUD промокодов + реферальная статистика |
| `core/repositories/user.py` | +4 метода (extend_subscription, extend_tarot, grant_premium, grant_tarot) |
| `core/models.py` | +модель PromoCode |
| `alembic/versions/` | +миграция add_promo_codes |
| `api/routes/web.py` | +применение промокода в create-payment и subscribe |
| `frontend/admin/index.html` | +модалка юзера, +таб Промокоды, +таб Рефералы, +KPI на дашборде |
| `frontend/pwa/app/profile.html` | +поле промокода при оплате (опционально, Фаза 2) |

---

## Ключевые правила для ВСЕХ субагентов

- НИКОГДА не добавляй комментарии
- Сохраняй стиль кода проекта (async/await, Pydantic v2, vanilla JS es5 без template literals)
- Всегда экранируй пользовательские данные в HTML (escapeHtml)
- После правок всегда проверяй ruff check
- Возвращай список изменённых файлов и результат проверки
