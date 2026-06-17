## NURA Light Theme — инструкция по деплою

### 1. nura-ds.css (полная замена файла)

Скопируй содержимое `nura-ds.css` из этого пакета и замени файл в репозитории:

```bash
# На локальном ПК (в корне репозитория)
cp /path/to/nura-ds.css ./nura-ds.css
```

Или открой `nura-ds.css` в редакторе и замени полностью.

---

### 2. index.html — замена блока [data-theme="light"]

В `index.html` найди существующий блок (начинается примерно так):

```css
    [data-theme="light"] {
      --bg: #F7F3ED;
```

И заканчивается перед `@media (max-width: 980px)` — удали всё
что относится к `[data-theme="light"]` в этой зоне и вставь
содержимое файла `index-light-theme.css`.

Проверь после вставки что в `<style>` нет дублей `[data-theme="light"]`.

---

### 3. PWA файлы — добавить в [data-theme="light"]

В каждом файле найди секцию `[data-theme="light"] { ... }` и
ДОБАВЬ в конец (перед закрывающей `}`) соответствующие правила
из файла `pwa-light-theme.css`.

Файлы и что добавить:

**frontend/pwa/app/tarot.html**
→ секции: "ОБЩЕЕ ДЛЯ ВСЕХ PWA ЭКРАНОВ" + "/app/tarot.html"

**frontend/pwa/app/index.html**
→ секции: "ОБЩЕЕ ДЛЯ ВСЕХ PWA ЭКРАНОВ" + "/app/index.html"

**frontend/pwa/app/chat.html**
→ секции: "ОБЩЕЕ ДЛЯ ВСЕХ PWA ЭКРАНОВ" + "/app/chat.html"

**frontend/pwa/app/profile.html**
→ секции: "ОБЩЕЕ ДЛЯ ВСЕХ PWA ЭКРАНОВ" + "/app/profile.html"

---

### 4. git commit + deploy

```bash
git add nura-ds.css index.html frontend/pwa/app/
git commit -m "fix: light theme — tokens + all pages (landing + PWA)"
git push origin main

# На VPS
bash /opt/nura/deploy.sh
```

---

### 5. Быстрая проверка после деплоя

Открой nura-ai.ru, переключи тему на светлую и проверь:

✅ Hero — персонаж Нуры виден на кремовом фоне (mix-blend-mode: multiply)
✅ Секция Матрица — зелёно-золотые карточки (#E2ECE6), читаемый текст
✅ Секция Таро — песочно-фиолетовые карточки (#EBE6DC), читаемый текст
✅ offer-buy (блок цены) — белый полупрозрачный фон
✅ /app/tarot — hero-card ТЁМНАЯ (#1C1814), spread-cards белые
✅ /app — matrix-card зелёная, day-card белая

### Если что-то не работает

Чаще всего причина — старый кэш браузера.
Принудительно: Ctrl+Shift+R (или Cmd+Shift+R на Mac)
