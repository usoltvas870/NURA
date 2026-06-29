# PWA Tarot UX Upgrade — Orchestrator Prompt

> Запустить из корня репозитория `C:\git\NURA`.
> Оркестратор управляет sub-agent'ами, координирует результаты, проверяет линтером.
> После завершения — `graphify update .` и обновить `STATE.md`.

## Фазы (выполнять последовательно, Фаза 1 → 2 → 3)

---

## Фаза 1 — Critical (немедленно)

### Задача 1.1: Skeleton + кэш для карты дня
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

Что сделать:
- Убрать хардкод `var cardData = { num: 'XIX', name: 'XIX · Солнце', ... }` — заменить на null
- Добавить skeleton-состояние при загрузке: CSS-класс `.skeleton` для `#hero-num`, `#hero-name`, `#hero-phrase`, `#hero-advice` (анимированный серый градиент)
- После успешного fetch — убрать skeleton, вставить данные
- При ошибке fetch — показать «Не удалось загрузить карту дня. Попробуй позже.»
- Кэшировать ответ API в localStorage по ключу `tarot_daily_card_<YYYY-MM-DD>`; при загрузке проверять кэш, показывать его мгновенно, затем обновлять через fetch
- Detail sheet (`openCardDetail`): если `cardData` = null — не открывать или показать «Загружается...»
- Skeleton CSS уже есть в nura-pwa.css (класс `.skeleton`, используется в index.html) — переиспользовать

Проверка:
- Открыть tarot.html — нет flash of wrong content
- Отключить сеть — карта дня грузится из localStorage
- Быстро тапнуть на hero — sheet не показывает хардкод

---

### Задача 1.2: Контекст Матрицы в карте дня
**Файлы:** `frontend/pwa/app/tarot.html`, `nura_app/api/routes/tarot_pwa.py`
**Sub-agent:** Frontend Developer + Backend Architect

Что сделать:
- API `GET /api/v1/tarot/daily-card` уже возвращает персонализированные данные
- Добавить в `DailyCardResponse` поля `user_archetype_name: str | None` и `user_archetype_number: int | None`
- В `api/routes/tarot_pwa.py:get_daily_card`: заполнять их из `user.main_archetype` и `user.main_archetype_number`
- В hero карты дня, под `arcane-advice`, добавить блок:
  ```html
  <div class="matrix-context" id="hero-matrix-context" style="display:none;margin-top:8px;font-size:11px;color:rgba(212,149,106,.70);text-shadow:0 1px 4px rgba(0,0,0,.4)">
    Этот аркан резонирует с твоим архетипом <strong id="matrix-archetype-name"></strong>
  </div>
  ```
- В JS: при получении `d.user_archetype_name` — показать блок и вставить имя

Проверка:
- У пользователя с Матрицей — под картой дня написано «Этот аркан резонирует с твоим архетипом Маг»
- У пользователя без Матрицы — блок скрыт

---

### Задача 1.3: Paywall — прямой платёж без лишнего тапа
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

Что сделать:
- В paywall sheet (`#pw-sheet`) заменить кнопку `location.href='profile.html#subscription'` на прямую:
  ```javascript
  onclick="subscribeTarot()"
  ```
- Функция `subscribeTarot()`:
  ```javascript
  window.subscribeTarot = function() {
    var btn = document.getElementById('pw-subscribe-btn');
    btn.disabled = true;
    btn.textContent = 'Загрузка...';
    fetch(NURA.BASE + '/web/subscribe', { method: 'POST', credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.payment_url) { window.location.href = d.payment_url; }
        else { showToast('Ошибка создания платежа'); btn.disabled = false; btn.textContent = 'Подключить подписку'; }
      })
      .catch(function() {
        showToast('Ошибка соединения'); btn.disabled = false; btn.textContent = 'Подключить подписку';
      });
  };
  ```
- Улучшить текст paywall: вместо текущего минимума — добавить список из 6 практик с эмодзи
- `onclick` для locked-практик: передавать название расклада в пейволл:
  ```html
  <article ... onclick="openPaywall('Расклад недели')">
  ```
- Paywall sheet: показывать название конкретной практики: «✦ Расклад недели — доступен по подписке»

Проверка:
- Нажатие на locked практику → paywall с названием этой практики
- Кнопка «Подключить» → редирект на YooKassa (или ошибка с восстановлением кнопки)

---

## Фаза 2 — Medium

### Задача 2.1: Визуальные экраны раскладов
**Файлы:** `frontend/pwa/app/tarot.html`, `frontend/pwa/app/nura-pwa.js`
**Sub-agent:** Frontend Developer

Что сделать:
- API `POST /api/v1/tarot/spread` уже возвращает `SpreadResponse` с `SpreadCard[]` — фронтенд сейчас его не вызывает
- Для каждого типа расклада (weekly, question, life, doubles, portal, yesno) — новый экран/секция
- После нажатия на разблокированную практику:
  1. Показать loading spinner
  2. Вызвать `POST /api/v1/tarot/spread` с `spread_type`
  3. Отобразить результат: заголовок, карты с номерами/названиями/интерпретациями, советы, summary, кнопка «Поделиться», кнопка «Ещё расклад»
- Использовать существующий sheet-механизм (как `#card-sheet`)
- Или отдельный `#spread-sheet` — переиспользовать стили

Проверка:
- Подписчик нажимает «Фокус недели» → видит 3 карты (Тело, Ум, Дух) с именами арканов и текстом
- Кнопка «Поделиться» работает
- Возврат к сетке практик

---

### Задача 2.2: Сетка практик — привести к спецификации
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

Сейчас: Фокус недели, Деньги, Отношения, Фокус месяца, Короткий ответ, Вопрос к NURA
Должно быть (из `tarot-integration-plan.md` и `bot-ux-map.md`):

| # | Эмодзи | Название | Описание | Тип расклада |
|---|--------|----------|----------|--------------|
| 1 | ✦ | Расклад недели | Тело · Ум · Дух | weekly |
| 2 | ◈ | По вопросу | Прошлое / Настоящее / Будущее | question |
| 3 | ✶ | Сферы жизни | Деньги / Отношения / Предназначение | life |
| 4 | ☯ | Двойники | Два аркана — внутренний диалог | doubles |
| 5 | 🌅 | Портал месяца | Чему научит / Что отпустить / Что усилить | portal |
| 6 | 👁 | Да / Нет | Один аркан — направление энергии | yesno |

- Обновить HTML-структуру `.practice-grid`
- Обновить JS-маппинг в `N.fetchJSON(BASE + '/web/me')`
- Для подписчиков: при клике не `askNura()`, а визуальный экран расклада (Задача 2.1)
- Обновить фоновые изображения под новые практики (или использовать существующие с новыми фильтрами)

Проверка:
- Сетка показывает 6 практик по спецификации
- Названия и описания понятны без контекста
- Замки работают
- Для подписчиков — визуальный экран расклада

---

### Задача 2.3: Заголовок и онбординг
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

- Заменить заголовок `.section-title` с «Практики на языке арканов» на «Таро-ритуалы»
- Добавить онбординг-блок для первого визита:
  ```html
  <div id="tarot-onboarding" class="card" style="display:none">
    <div class="eyebrow">Добро пожаловать в Таро</div>
    <p>Каждый день — новая карта. На основе твоей даты рождения и архетипа. Смотри, анализируй, применяй.</p>
    <button onclick="dismissOnboarding()">Понятно →</button>
  </div>
  ```
- Показывать если `localStorage.getItem('tarot_onboarding_done')` !== '1'
- После показа установить `localStorage.setItem('tarot_onboarding_done', '1')`
- Заменить дисклеймер — с оборонительного на вдохновляющий:
  «Твоя карта дня — не предсказание, а зеркало. Возьми главный вопрос дня и примерь к нему смысл аркана.»

Проверка:
- При первом открытии — онбординг виден
- При втором — нет
- Заголовок — «Таро-ритуалы»
- Дисклеймер — вдохновляющий тон

---

### Задача 2.4: Install banner на tarot.html
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

- Добавить `<script src="/pwa-install.js"></script>` перед закрывающим `</body>`
- Добавить HTML-блоки для Android-install и iOS-install (как на index.html)
- Показывать после успешной загрузки карты дня (не при первом входе — через localStorage счётчик визитов)

Проверка:
- На Android Chrome — предложение установки после 3-го просмотра карты дня
- На iOS — инструкция по установке

---

## Фаза 3 — Low (улучшения)

### Задача 3.1: Стреак-счётчик
**Файлы:** `frontend/pwa/app/tarot.html`
**Sub-agent:** Frontend Developer

- localStorage счётчик `tarot_streak`:
  - При загрузке карты дня: проверить `tarot_last_date`. Если вчера → streak+1. Если сегодня → ничего. Если раньше → streak=1.
- Показывать в hero: «🔥 5 дней подряд»
- Сброс при пропуске дня

### Задача 3.2: Авто-редирект после оплаты
**Файлы:** `nura_app/api/routes/web.py`, `frontend/pwa/app/success.html`, `frontend/pwa/app/tarot.html`
**Sub-agent:** Backend Architect

- После успешной оплаты YooKassa webhook → редирект на `/app/tarot?subscribed=1`
- На `tarot.html` проверить `?subscribed=1` и показать toast «Подписка активна!» + перезагрузить статус

### Задача 3.3: Кэш статики в Service Worker
**Файлы:** `frontend/service-worker.js`
**Sub-agent:** Frontend Developer

- Добавить `/app/tarot.html` в `STATIC_ASSETS` в service-worker.js

---

## Порядок запуска sub-agent'ов

```
Фаза 1:
  Frontend Developer → Задача 1.1 + 1.2 + 1.3 (параллельно 3 sub-agent'а или 1 с последовательными правками)

Фаза 2:
  Frontend Developer → Задача 2.1 (самая объёмная, может потребовать 2 sub-agent'а: HTML/CSS и JS/API)
  Frontend Developer → Задача 2.2 + 2.3 + 2.4 (параллельно, 2-3 sub-agent'а)

Фаза 3:
  Frontend Developer → Задача 3.1 + 3.3
  Backend Architect  → Задача 3.2

После каждой фазы:
  ruff check frontend/pwa/app/tarot.html frontend/pwa/app/nura-pwa.js --select F
После всех фаз: graphify update .
```

## Критерии готовности

- [ ] Нет хардкода «XIX · Солнце» в tarot.html
- [ ] Skeleton при загрузке, кэш в localStorage
- [ ] Контекст Матрицы под картой дня
- [ ] Paywall с прямым платёжом и контекстным описанием
- [ ] 6 практик по спецификации с визуальными экранами раскладов
- [ ] Онбординг для первого визита
- [ ] Install banner
- [ ] Весь код проходит `ruff check`
