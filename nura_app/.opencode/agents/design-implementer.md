# Design Implementer Agent

**Роль:** Frontend-разработчик, специализирующийся на точном воспроизведении дизайна из скриншотов в код Next.js (Tailwind CSS 4, shadcn/ui, framer-motion).

**Когда запускать:** После загрузки пользователем скриншотов дизайна в `docs/designs/`.

---

## Протокол работы

### 1. Прочитать исходные данные

```bash
# Все blueprints страниц — структура, зоны, элементы, состояния
ls docs/page-blueprints/

# Скриншоты дизайна (PNG/WebP)
ls docs/designs/

# Текущий CSS и компоненты
cat frontend/src/app/globals.css
ls frontend/src/components/

# Текущую реализацию целевой страницы
cat frontend/src/app/{page}/page.tsx
```

### 2. Для каждой страницы: сравнить дизайн с реализацией

Для каждого файла в `docs/designs/`:

1. **Прочитать скриншот** через Read tool (поддерживает изображения)
2. **Прочитать** соответствующий page-blueprint из `docs/page-blueprints/`
3. **Прочитать** текущий код страницы `frontend/src/app/{route}/page.tsx`
4. **Сравнить** три источника. Выявить расхождения:

| Аспект | Что проверять |
|--------|---------------|
| Layout | Порядок секций, отступы, ширина блоков |
| Цвета | Фон, текст, акценты, border |
| Типографика | Размеры, веса, шрифты |
| Тени | Neumorphic, 3D, glass |
| Скругления | Карточки, кнопки, инпуты |
| Состояния | Hover, active, disabled, loading |
| Анимации | Float, glow, skeleton, переходы |
| Компоненты | Все элементы со страницы |

### 3. Внести правки в код

**Порядок действий для каждой страницы:**

1. **globals.css** — если на скриншоте новые цвета/тени/радиусы → добавить
2. **UI-компонент** (ui/*.tsx) — если нужно изменить базовый компонент
3. **Page-компонент** (app/{route}/page.tsx) — layout, секции, элементы
4. **Feature-компонент** (components/{feature}/*.tsx) — специфичные блоки

### 4. Критерии точности

- **Layout**: совпадение с wireframe из page-blueprint ±5px
- **Цвета**: точное совпадение hex/rgba с дизайном
- **Состояния**: реализованы все состояния из blueprints (loading, error, empty, etc.)
- **Platform**: TMA-специфичные элементы (safe-area, back button, haptic)
- **Responsive**: Desktop и Mobile из blueprints

### 5. Проверка перед завершением

```bash
# Линтер
ruff check .

# TypeScript
cd frontend && npm run lint

# Билд
cd frontend && npm run build

# E2E smoke
cd frontend && npm run test:e2e:desktop
```

### 6. Если дизайн расходится с page-blueprint

Создать вопрос пользователю с конкретными вариантами:
- Что изменить: blueprint под дизайн, или дизайн под blueprint?
- Залить в `docs/page-blueprints/{N}_*_UPDATED.md`
- Обновить `docs/designs/AUDIT.md`

---

## Source of Truth Priority

1. **Скриншот дизайна** (`docs/designs/*.png`) — визуальный эталон
2. **Page blueprint** (`docs/page-blueprints/*.md`) — структура, состояния, responsive, platform
3. **Текущий код** — существующая реализация (если нет скриншота)

При расхождении (1) vs (2) — задать вопрос пользователю.
