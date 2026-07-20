# PWA Implementation Rules

Эти правила определяют безопасное изменение PWA. Для визуального направления см. [PWA North Star Design](PWA_NORTH_STAR_DESIGN.md), для наблюдаемых сценариев — [PWA Page Contracts](PWA_PAGE_CONTRACTS.md).

## Scope и файлы

Рабочая PWA находится в [frontend/pwa/app](../../frontend/pwa/app). Общие файлы — [nura-pwa.js](../../frontend/pwa/app/nura-pwa.js), [nura-pwa.css](../../frontend/pwa/app/nura-pwa.css), [nura-shell-v1.css](../../frontend/pwa/app/nura-shell-v1.css), [theme.css](../../theme.css), [pwa-install.js](../../frontend/pwa-install.js) и [service-worker.js](../../frontend/service-worker.js). Метаданные релиза генерирует [scripts/build_pwa_release.py](../../scripts/build_pwa_release.py) в [pwa-release.js](../../frontend/pwa/pwa-release.js) и [pwa-release.json](../../frontend/pwa/pwa-release.json).

## CSS

Home подключает локальные шрифты, `nura-pwa.css`, `theme.css`, `home-v8.css` и `home-v9.css`. Tarot, Chat и Profile подключают локальные шрифты, `nura-pwa.css`, `theme.css`, `nura-shell-v1.css` и соответственно `tarot-v2-1.css`, `chat-v1-2.css`, `profile-v1.css`. Это фактические imports текущих страниц, а не вывод из preview.

Page-specific изменение остаётся в page CSS, когда это возможно. Изменение shared CSS требует cross-page regression review. Не возрождать отброшенные локальные изменения `nura-pwa.css`; inline styles не расширять без осознанной необходимости. Сохранять light/dark поведение и при material visual change проверять 360, 390, 430 px и desktop.

## JavaScript и навигация

Каждая активная страница подключает `nura-pwa.js` и содержит page-specific inline script; Home и Tarot также подключают `pwa-install.js`. Сохраняйте hooks, IDs и `data-*` атрибуты. Навигационный параметр не выполняет Chat-запрос автоматически: вопрос может только заполнить input. Списание квоты начинается лишь после явного submit.

Ask NURA использует consume-once transport: URL-параметр, затем fallback `localStorage.nura_pending_question`; после потребления URL очищается и fallback удаляется. Daily Tarot использует `tarot.html?open=daily` и потребляет параметр только после получения доступного payload. Пока access/auth/loading состояние не подтверждено, защищённые действия не должны быть доступны.

## Access states

Не добавляйте выдуманных access-state. Текущий код различает loading, guest и подтверждённое пользовательское состояние с доступом/квотами. Loading блокирует защищённые действия; Matrix, Ask NURA и Daily следуют существующему auth-flow, Profile остаётся доступен по своей активной route. При исчерпании квоты Chat сохраняет читаемую историю там, где она уже отрисована; badges и access labels должны отражать реальное состояние.

## Tarot mapping

Backend и PWA используют номера 1–22; Шут — номер 22, не 0. Исторические filenames намеренно не совпадают с русскими названиями: `8 → 08-justice.png → «Сила»`, `11 → 11-strength.png → «Справедливость»`. Не переименовывать их без согласованной backend/frontend миграции. Все 22 утверждённые PNG защищены; оптимизация изображений — отдельная задача.

## Release metadata и service worker

`python scripts/build_pwa_release.py --check` проверяет детерминированную карту. Release ID строится только из tracked текстовых assets в `ASSETS`; Major Arcana PNG намеренно находятся вне release asset map. [frontend/test_pwa_release.mjs](../../frontend/test_pwa_release.mjs) проверяет карту, release script, service worker и 22 защищённых изображения. Не изменяйте service worker инцидентно.

## Проверки и Git safety

Используйте `git diff --check`, `python scripts/build_pwa_release.py --check`, `node frontend/test_pwa_release.mjs`, а из `nura_app/` — `pytest tests/test_build_pwa_release.py tests/test_pwa_personas_e2e.py tests/test_ios_install_dialogs_e2e.py -v`. Inline-script syntax проверяется только подходящим уже доступным локальным инструментом; отдельного repository script для неё нет. Remote CI остаётся обязательной финальной проверкой.

Начинайте от точного `origin/main`, используйте isolated worktree, stage paths явно и никогда не применяйте `git add .`. Не force-push, не смешивайте deploy с implementation PR; для visual/product merge требуется одобрение владельца.
