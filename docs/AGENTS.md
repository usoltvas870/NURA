# NURA Docs — Agent Rules

## Authority map

- `docs/README.md` — главный router авторитетности.
- `product/NURA_1_0_1_5_PRODUCT_SPEC.md` — canonical target; не гарантия реализации и не редактируется без отдельной задачи.
- `implementation/current-status.md` — evidence-backed зеркало current code/tests/config, не нормативная спецификация.
- `decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md` — решения владельца по этой миграции, не замена product spec.
- `acceptance/` отделяет local, external sandbox и production evidence.
- `archive/` — legacy/superseded history; не использовать как current contract.
- `vision/` — future vision, не committed roadmap.
- `reconciliation/` — dated audit evidence и migration history.

При расхождении target, current-status и code сообщи о конфликте. Code/tests/config имеют приоритет для implemented state; product spec — для target state. Не расширяй NURA 1.0 функциями 1.5 и не восстанавливай старую PWA/pricing model по архивным документам.

## Changes

Сохраняй историю и ссылки, не создавай второй canonical product spec. Для mixed-документов не выбирай current/legacy/future молча. `STATE.md` обновляй только по root policy; Stage 2A его не меняет из-за внешнего dirty diff.

## Graphify

Документационная реорганизация без production architecture change не требует `graphify update`. Generated graph output не включай в несвязанный diff.
