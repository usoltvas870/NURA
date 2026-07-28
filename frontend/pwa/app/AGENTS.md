# NURA PWA — Agent Rules

## Status and sources

PWA — legacy compatibility client, а не текущий product roadmap. Product authority: `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md`; implemented status: `docs/implementation/current-status.md`.

Для безопасной поддержки используй:

- `docs/archive/legacy-pwa/README.md`;
- `docs/archive/legacy-pwa/architecture/PWA_NORTH_STAR_DESIGN.md`;
- `docs/archive/legacy-pwa/architecture/PWA_PAGE_CONTRACTS.md`;
- `docs/archive/legacy-pwa/architecture/PWA_IMPLEMENTATION_RULES.md`.

Legacy-документы разрешают compatibility maintenance, но не расширение NURA 1.0/1.5.

## Scope and safety

- Не меняй несколько PWA-страниц за одну итерацию без прямого запроса.
- Сохраняй `id`, `data-*`, global functions и JS hooks.
- В визуальной задаче не меняй auth, payment, install logic, manifest или service worker.
- Не выводи пользовательский ввод через `innerHTML`; используй безопасные DOM APIs и escaping.
- Prototype не подключай к production без отдельной задачи.

## Required QA after PWA changes

- Viewports: `360×800`, `390×844`, `430×932`.
- Нет horizontal overflow, console errors или 404.
- Tabbar/safe-area/sticky elements не перекрывают контент.
- При необходимости проверь mobile keyboard/composer и guest/full/subscriber states.
- Подтверди сохранность JS hooks сравнением до/после.

## Image generation

Генерируй сложные декоративные visuals только по явной задаче. Не превращай layout, buttons и базовые icons в raster assets; production assets требуют отдельного визуального утверждения.
