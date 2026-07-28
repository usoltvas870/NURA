# NURA: текущее состояние реализации

**Статус:** CURRENT IMPLEMENTATION MIRROR — EVIDENCE-BACKED, NON-NORMATIVE
**Проверено:** 2026-07-28
**Baseline:** воспроизводимый committed code baseline branch `main`, HEAD `b70d6ccf8bbeac49b77015be09295a41060fc9bd`
**Назначение:** кратко отвечать на вопрос «что фактически реализовано сейчас» по коду, миграциям, конфигурации и тестам.

Этот документ не определяет product scope и не заменяет [каноническую спецификацию](../product/NURA_1_0_1_5_PRODUCT_SPEC.md). Расхождение с target называется implementation gap. Code/test состояние воспроизводится из указанного commit; на момент его фиксации в worktree оставались документационная миграция и ранее изменённый `STATE.md`. В code baseline вошли refund fence, нормализованный audit status, exact commit-scope contract и fail-closed cleanup gate. Подтверждённый evidence: targeted tests — `147 passed`; PostgreSQL race coverage — `3 passed`; safe suite — `1081 passed`, `22 skipped`, `1 deselected`, `0 failed`; Ruff — PASS; independent review — no actionable findings. После material code/config changes документ требует повторной evidence-проверки. Статус `READY` означает наличие локально подтверждённой реализации и не означает sandbox или production readiness.

## Статусы

- `READY` — основной implementation contract существует и покрыт релевантным локальным evidence.
- `PARTIAL` — часть пути реализована, но target contract или обязательная граница неполны.
- `NOT_IMPLEMENTED` — подтверждающая реализация не найдена.
- `LEGACY` — код существует для обратной совместимости или прежней продуктовой модели и не управляет текущим roadmap.
- `UNKNOWN` — данных недостаточно без внешней или отдельной технической проверки.

## Матрица функций

| Функция | Статус | Версия | Evidence в коде/тестах | Implementation gap | Feature flag | Видима пользователю |
|---|---|---|---|---|---|---|
| Telegram onboarding | `PARTIAL` | 1.0 | `nura_app/bot/handlers/start.py`, `nura_app/bot/handlers/onboarding.py`, `nura_app/tests/test_telegram_first_postgres_golden_path.py` | Consent и дата рождения есть; отдельное обязательное имя не собирается, используется Telegram profile | нет | да |
| Mini-report | `READY` | 1.0 | `nura_app/core/services/mini_report_application.py`, `nura_app/core/services/telegram_report_delivery.py`, `nura_app/tests/test_mini_report_application.py`, `nura_app/tests/test_mini_report_telegram_delivery.py` | Нужны внешний content review и Telegram sandbox, но локальный durable path реализован | нет | да |
| Полный отчёт | `PARTIAL` | 1.0 | `nura_app/core/services/matrix_report_worker.py`, `nura_app/core/services/full_report_telegram_delivery.py`, `nura_app/tests/test_matrix_report_worker_lifecycle.py`, `nura_app/tests/test_full_report_telegram_delivery.py` | Durable PDF реализован; обязательная текстовая выдача полного отчёта в Telegram отсутствует | нет | да |
| YooKassa one-time checkout 890 ₽ | `READY` | 1.0 | `nura_app/core/services/full_matrix_checkout.py`, `nura_app/api/routes/payment.py`, `nura_app/tests/test_full_matrix_checkout.py`, `nura_app/tests/test_payment_webhook_verification.py` | Реальный test-shop/webhook/receipt sandbox не выполнялся | нет | да |
| Текстовая выдача | `PARTIAL` | 1.0 | `nura_app/core/services/telegram_report_delivery.py`, `nura_app/core/services/full_report_telegram_delivery.py` | Mini имеет текст + PDF; full delivery отправляет PDF без обязательного полного текста | нет | да |
| PDF | `READY` | 1.0 | `nura_app/core/services/pdf.py`, `nura_app/core/services/telegram_report_delivery.py`, `nura_app/core/services/full_report_telegram_delivery.py`, report tests | Production distribution/size и внешний delivery не подтверждены | нет | да |
| My materials / «Мои разборы» | `PARTIAL` | 1.0 | `nura_app/bot/handlers/profile.py`, `nura_app/core/services/my_reports.py`, `nura_app/tests/test_my_reports.py` | Mini/full list и resend есть; naming и полная target taxonomy материалов не совпадают | нет | да |
| Free-чат и квота | `PARTIAL` | 1.0 | `nura_app/core/services/chat_quota.py`, `nura_app/core/services/chat_application.py`, `nura_app/tests/test_lifetime_chat_contract.py` | Реализовано 5 lifetime-сообщений; target требует 5 успешных ответов каждый день с reset в `Europe/Moscow` и configurable limit/timezone | нет | да |
| Карта дня | `READY` | 1.0 | `nura_app/core/services/daily_tarot_application.py`, `nura_app/bot/handlers/tarot.py`, `nura_app/tests/test_daily_tarot_application.py` | Внешний Telegram UX и production schedule отдельно не подтверждены | нет | да |
| Broadcasts | `PARTIAL` | 1.0 | `nura_app/api/routes/admin_api.py`, `nura_app/core/tasks.py`, `nura_app/tests/test_celery_async_task_contract.py` | Есть transport/admin start/status; нет persisted campaign/delivery, Telegram opt-out, suppression, frequency cap и CTA analytics | нет | только через admin trigger / сообщения получателям |
| Подарок 30 дней | `NOT_IMPLEMENTED` | 1.5A | `nura_app/core/models.py`, migrations — отдельный gift entitlement не найден | Нет gift activation, срока и migration rule ранних покупателей | нет | нет |
| Доступ 399 ₽ / 30 дней | `NOT_IMPLEMENTED` | 1.5A | `nura_app/core/config.py`, `nura_app/core/services/payment.py` | Target 399 без автопродления отсутствует | нет | нет |
| Legacy-подписка 390 ₽ / recurring | `LEGACY` | вне target 1.0/1.5 baseline | `nura_app/core/config.py`, `nura_app/core/services/payment.py`, `nura_app/core/tasks.py`, payment handlers | Конфликтует с target; migration/disposition и скрытие из основного UX не завершены | отдельного flag не найдено | да в legacy surfaces |
| Tarot spreads | `PARTIAL` | 1.5A | `nura_app/bot/handlers/tarot.py`, `nura_app/api/routes/tarot_pwa.py`, `nura_app/core/prompts/tarot/` | Несколько flows существуют раньше релиза; accepted set, durable TarotReading/history и target monetization не завершены | отдельного 1.5 flag не найдено | да в legacy/ранних surfaces |
| Compatibility | `LEGACY` | target 1.5B | `nura_app/bot/handlers/compatibility.py`, compatibility tests | Реализация опережает target; нет принятого 1.5B release/gating и окончательных privacy rules | отдельного flag не найдено | да |
| Referral | `PARTIAL` | target 1.5B | `nura_app/core/models.py` (`ReferralReward`), referral/start handlers | Foundation существует; reward contract, anti-fraud и release gating не приняты | отдельного flag не найдено | частично |
| PWA | `LEGACY` | compatibility | `frontend/pwa/app/`, `nura_app/api/routes/web.py`, PWA tests | Не является основным клиентом; срок deprecation и compatibility boundary требуют отдельного решения | нет | да |
| Email/VK/guest auth | `LEGACY` | compatibility | `nura_app/api/routes/auth.py`, `nura_app/core/services/auth.py`, `nura_app/tests/test_auth.py` | Работает как web compatibility, но не входит в Telegram-first funnel | нет | да через legacy web |
| Web report links | `LEGACY` | compatibility | `nura_app/api/routes/reports.py`, `nura_app/bot/handlers/payment.py` | Tokenized HTML/PDF routes активны, но target delivery не должен требовать web-ссылку | нет | да |
| Runtime prompts | `PARTIAL` | 1.0 | `nura_app/core/prompts/system_prompt.txt`, `nura_app/core/prompts/chat_system_prompt.txt`, loaders в `nura_app/core/services/ai.py` | Исполняемые prompts есть; утверждённый раздельный runtime style contract для report/chat не оформлен | нет | опосредованно |
| Product analytics | `PARTIAL` | 1.0 | `nura_app/core/services/attribution.py`, `AttributionLink`/`AttributionTouch`, attribution tests | Acquisition attribution есть; канонического event registry и KPI queries для funnel/payment/report/chat/broadcast нет | нет | нет |
| Support/admin | `READY` | operations | `nura_app/api/routes/admin_api.py`, `nura_app/admin_bot/` | Часть операций subscription-centric; production access/permissions отдельно не проверялись | нет | только operator/admin |
| External sandbox | `UNKNOWN` | release gate | `docs/acceptance/` после миграции, local acceptance tools | Telegram test bot, YooKassa test shop, HTTPS and legal/support evidence отсутствуют | не применимо | нет |

## Ключевые implementation gaps NURA 1.0

1. Daily Free-chat quota вместо текущего lifetime ledger.
2. Полный отчёт текстом в Telegram наряду с PDF.
3. Минимальный persisted broadcast/campaign delivery, opt-out и analytics contract.
4. Канонический runtime style layer отдельно для report и chat consumers.
5. Скрытие или migration disposition legacy 390/recurring, расширенного Tarot и других ранних 1.5 surfaces.
6. Внешняя Telegram/YooKassa sandbox и production/legal/infrastructure acceptance.

## Правило обновления

Обновляй эту матрицу только после проверки фактического code/test/config evidence. Product target меняется только через отдельную задачу на каноническую спецификацию; roadmap checkbox или исторический документ не доказывает реализацию.
