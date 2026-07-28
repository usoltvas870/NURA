# NURA documentation reconciliation: итог Этапа 1

**STATUS: DATED RECONCILIATION EVIDENCE — NON-NORMATIVE**

## Результат

Аудит охватил 180 документальных артефактов: 178 файлов репозитория и 2 приложенных canonical-файла. Дополнительно как evidence inspected: Python code, migrations, configuration, API routes, bot handlers, services, repositories, Celery tasks, templates, deployment contracts и tests. Runtime prompts использовались как исполняемые контракты, но не считались документацией. Один чужой readiness-review появился в shared worktree во время аудита и был включён без редактирования.

Документация находится в состоянии **высокого semantic drift**: сильные current technical/operations документы сосуществуют с PWA-first product contracts, историческими patch-файлами, устаревшей pricing/subscription model и generated/tool documentation без authority boundary.

## Категории

| Категория | Документов |
|---|---:|
| `CURRENT_IMPLEMENTED_STATE` | 6 |
| `CANONICAL_TARGET_PRODUCT` | 2 |
| `CURRENT_TECHNICAL_DOCUMENTATION` | 104 |
| `LEGACY_PWA` | 12 |
| `FUTURE_PLATFORM_VISION` | 8 |
| `SUPERSEDED` | 36 |
| `MIXED` | 12 |
| `UNKNOWN_REQUIRES_DECISION` | 0 |
| **Всего** | **180** |

Большое число `CURRENT_TECHNICAL_DOCUMENTATION` объясняется agent/skill/design instruction files; это не число продуктовых контрактов.

## Конфликты

Всего 30: `DOC_VS_CODE` 9, `DOC_VS_DOC` 6, `LEGACY_VS_CURRENT` 5, `CURRENT_VS_TARGET` 7, `PRODUCT_DECISION_REQUIRED` 2, `TECHNICAL_VERIFICATION_REQUIRED` 1.

Критические:

1. PWA-core и Telegram-first одновременно представлены как current.
2. 390 ₽ recurring subscription в code/docs против target 399 ₽ voluntary 30-day access только в 1.5.
3. Full report доставляется PDF, но не текстом в Telegram.
4. Canonical runtime prompt layer отсутствует.
5. Broadcast foundation не достигает 1.0 campaign/opt-out/analytics acceptance.
6. Production readiness нельзя вывести из local repository status.

## Подтверждённый current baseline

Telegram onboarding/consent, mini text+PDF, full-matrix 890 checkout, YooKassa verification/idempotency, durable report generation/PDF delivery/retry, «Мои разборы», lifetime shared 5-message quota, daily card, attribution и базовый broadcast transport существуют. Targeted local observation: **148 passed**, exit code 0, 33,30 с; это не full suite и не production proof.

Legacy active: PWA/web auth/report delivery, web funnel CTA, 390 subscription/recurring payment, expanded Tarot/compatibility/referral foundations.

## Главные риски

- Codex или разработчик может реализовать противоположную product model, читая `platform-strategy.md`, `pricing.md`, bot specs или PWA patches.
- «Актуален» в `docs/README.md` сейчас не означает соответствие canonical target.
- Current implementation journal (`STATE.md`) слишком велик и смешивает history, decisions и status.
- Отсутствующие ссылки и дубли подрывают навигацию.
- Local test evidence может быть ошибочно принято за production acceptance.

## Рекомендуемая последовательность Этапа 2

1. Принять OD-01..OD-04 и OD-10/OD-12, влияющие на migration boundaries.
2. Внести canonical Markdown в `docs/product/` и сделать `docs/README.md` authority router.
3. Создать `implementation/current-status.md` и acceptance index из этого аудита.
4. Архивировать PWA-first product/plan docs с legacy index; не удалять полезные technical contracts.
5. Разделить `MIXED`: bot, pricing, reports, prompts, Tarot, STATE/PLAN.
6. Создать минимальные architecture contracts: Telegram, payments-entitlements, reports, chat, broadcasts-lifecycle.
7. Исправить broken links/duplicates/mojibake, затем запустить link/integrity checks.
8. Только после documentation authority cleanup декомпозировать implementation gaps NURA 1.0.

Этап 2 в рамках этой задачи не начат.

## Проверки и ограничения

- 2026-07-28, cwd `C:/git/NURA/nura_app`, branch `main`, HEAD `61977175ef3b88fad618674fca2554db60aae379`, исходный dirty worktree: `$env:APP_ENV='test'; pytest tests/test_attribution.py tests/test_lifetime_chat_contract.py tests/test_daily_tarot_application.py tests/test_mini_report_application.py tests/test_mini_report_telegram_delivery.py tests/test_full_matrix_checkout.py tests/test_matrix_report_worker_lifecycle.py tests/test_full_report_telegram_delivery.py tests/test_payment_webhook_verification.py tests/test_my_reports.py -q` → exit code 0, 148 passed in 33.30s. Concurrent readiness-review появился позже и не входил в baseline; full suite не запускался.
- DOCX semantic comparison: 99,7% normalized Markdown coverage; DOCX не повышен до отдельного source of truth.
- PDF metadata/text inspected; два 46-page PDF являются byte-identical.
- Secrets не читались и не выводились.
- Graphify update не требуется: архитектура/код не менялись; `STATE.md` не обновлялся.
- Existing code/docs не редактировались, не перемещались, не удалялись.
