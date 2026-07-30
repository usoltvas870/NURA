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
- `NOT_EXECUTED` — требуемая внешняя или операционная проверка известна, но accepted execution evidence отсутствует.
- `UNKNOWN` — данных недостаточно без внешней или отдельной технической проверки.

## Матрица функций

| Функция | Статус | Версия | Evidence в коде/тестах | Implementation gap | Feature flag | Видима пользователю |
|---|---|---|---|---|---|---|
| Telegram onboarding | `PARTIAL` | 1.0 | `nura_app/bot/handlers/start.py`, `nura_app/bot/handlers/onboarding.py`, `nura_app/tests/test_telegram_first_postgres_golden_path.py` | Consent и дата рождения есть; отдельное обязательное имя не собирается, используется Telegram profile | нет | да |
| Mini-report | `READY` | 1.0 | `nura_app/core/services/mini_report_application.py`, `nura_app/core/services/telegram_report_delivery.py`, `nura_app/tests/test_mini_report_application.py`, `nura_app/tests/test_mini_report_telegram_delivery.py` | Нужны внешний content review и Telegram sandbox, но локальный durable path реализован | нет | да |
| Полный отчёт | `READY (local)` | 1.0 | `nura_app/core/services/matrix_report_worker.py`, `nura_app/core/services/full_report_telegram_delivery.py`, `nura_app/tests/test_full_report_telegram_delivery.py` | Durable full text + PDF: immutable snapshot, chunk progress, retry and refund fence; external sandbox не выполнялся | нет | да |
| YooKassa one-time checkout 890 ₽ | `READY` | 1.0 | `nura_app/core/services/full_matrix_checkout.py`, `nura_app/api/routes/payment.py`, `nura_app/tests/test_full_matrix_checkout.py`, `nura_app/tests/test_payment_webhook_verification.py` | Реальный test-shop/webhook/receipt sandbox не выполнялся | нет | да |
| Текстовая выдача | `READY (local)` | 1.0 | `nura_app/core/services/full_report_telegram_delivery.py` | Full delivery строит только из persisted `ai_analysis`, отправляет canonical sections до PDF и не использует `kitchen_analysis` | нет | да |
| PDF | `READY` | 1.0 | `nura_app/core/services/pdf.py`, `nura_app/core/services/telegram_report_delivery.py`, `nura_app/core/services/full_report_telegram_delivery.py`, report tests | Production distribution/size и внешний delivery не подтверждены | нет | да |
| My materials / «Мои разборы» | `PARTIAL` | 1.0 | `nura_app/bot/handlers/profile.py`, `nura_app/core/services/my_reports.py`, `nura_app/tests/test_my_reports.py` | Mini/full list и resend есть; naming и полная target taxonomy материалов не совпадают | нет | да |
| Free-чат и квота | `PARTIAL` | 1.0 | `nura_app/core/services/chat_quota.py`, `nura_app/core/services/chat_application.py`, `nura_app/tests/test_lifetime_chat_contract.py`, `nura_app/tests/test_web_chat_quota.py` | Общий Telegram/web ledger даёт пять календарных committed-ответов в `Europe/Moscow`; provider/history/send failure не создаёт consumed usage. Не хватает durable transport retry/progress для failed и multipart Telegram delivery, а web HTTP-response не имеет client ACK | нет | да |
| Карта дня | `READY` | 1.0 | `nura_app/core/services/daily_tarot_application.py`, `nura_app/bot/handlers/tarot.py`, `nura_app/tests/test_daily_tarot_application.py` | Внешний Telegram UX и production schedule отдельно не подтверждены | нет | да |
| Broadcasts | `PARTIAL` | 1.0 | `nura_app/api/routes/admin_api.py`, `nura_app/core/tasks.py`, `nura_app/tests/test_celery_async_task_contract.py` | Есть transport/admin start/status; нет persisted campaign/delivery, Telegram opt-out, suppression, frequency cap и CTA analytics | нет | только через admin trigger / сообщения получателям |
| Подарок 30 дней | `NOT_IMPLEMENTED` | 1.5A | `nura_app/core/models.py`, migrations — отдельный gift entitlement не найден | Нет gift activation, срока и migration rule ранних покупателей | нет | нет |
| Доступ 399 ₽ / 30 дней | `NOT_IMPLEMENTED` | 1.5A | `nura_app/core/config.py`, `nura_app/core/services/payment.py` | Target 399 без автопродления отсутствует | нет | нет |
| Legacy-подписка 390 ₽ / recurring | `LEGACY` | вне target 1.0/1.5 baseline | `nura_app/core/config.py`, `nura_app/core/services/payment.py`, `nura_app/core/tasks.py`, payment handlers | Конфликтует с target; migration/disposition и скрытие из основного UX не завершены | отдельного flag не найдено | да в legacy surfaces |
| Tarot spreads | `PARTIAL` | 1.5A | `nura_app/bot/handlers/tarot.py`, `nura_app/api/routes/tarot_pwa.py`, `nura_app/core/prompts/tarot/` | Flows сохранены, но Telegram primary path и direct callbacks закрыты флагом `enable_expanded_tarot` по умолчанию | `enable_expanded_tarot` (false) | нет |
| Compatibility | `LEGACY` | target 1.5B | `nura_app/bot/handlers/compatibility.py`, release-boundary tests | Реализация сохранена, но menu и callbacks закрыты флагом `enable_compatibility` по умолчанию | `enable_compatibility` (false) | нет |
| Referral | `PARTIAL` | target 1.5B | `nura_app/core/models.py` (`ReferralReward`), referral/start handlers | Attribution parsing `ref_` сохранён; публичная ссылка и reward processing закрыты `enable_referral_promotion` | `enable_referral_promotion` (false) | нет |
| PWA | `LEGACY` | compatibility | `frontend/pwa/app/`, `nura_app/api/routes/web.py`, PWA tests | Не является основным клиентом; срок deprecation и compatibility boundary требуют отдельного решения | нет | да |
| Guest auth | `LEGACY` | compatibility | `nura_app/api/routes/auth.py`, `nura_app/core/services/auth.py`, `nura_app/tests/test_auth.py` | Current legacy web compatibility path; не входит в Telegram-first identity funnel | нет | да через legacy web |
| VK auth | `LEGACY` | compatibility | `nura_app/api/routes/auth.py`, `nura_app/core/services/auth.py`, mocked provider coverage в `nura_app/tests/test_auth.py` | Current legacy web compatibility path; внешний VK provider/configuration отдельно не подтверждён | нет | да через legacy web |
| Email magic-link auth | `PARTIAL` | compatibility | `AuthService.start_email_auth()`/`verify_magic_link()`, email verification/guest merge foundation и local service tests | Production verify route ставит session cookie на injected `Response`, затем возвращает отдельный `RedirectResponse`; cookie не переносится, поэтому end-to-end email login session имеет active wiring gap | нет | route видим, рабочая session не доказана |
| Web report links | `LEGACY` | compatibility | `nura_app/api/routes/reports.py`, `nura_app/bot/handlers/payment.py` | Tokenized HTML/PDF routes активны, но target delivery не должен требовать web-ссылку | нет | да |
| Runtime prompts | `PARTIAL` | 1.0 | `nura_app/core/prompts/system_prompt.txt`, `nura_app/core/prompts/chat_system_prompt.txt`, loaders в `nura_app/core/services/ai.py` | Исполняемые prompts есть; утверждённый раздельный runtime style contract для report/chat не оформлен | нет | опосредованно |
| Product analytics | `PARTIAL` | 1.0 | `nura_app/core/services/attribution.py`, `AttributionLink`/`AttributionTouch`, attribution tests | Acquisition attribution есть; канонического event registry и KPI queries для funnel/payment/report/chat/broadcast нет | нет | нет |
| Support/admin | `READY` | operations | `nura_app/api/routes/admin_api.py`, `nura_app/admin_bot/` | Часть операций subscription-centric; production access/permissions отдельно не проверялись | нет | только operator/admin |
| External sandbox | `NOT_EXECUTED` | release gate | [acceptance evidence router](../acceptance/README.md), local acceptance tools и [external sandbox runbook](../acceptance/telegram-first-sandbox.md) | Telegram test bot, YooKassa test shop, external AI/provider, HTTPS and legal/support evidence отсутствуют | не применимо | нет |

## Local chat-delivery update (2026-07-30)

`READY` locally for the narrow free-chat delivery contract: durable Telegram multipart progress/retry, terminal release, exactly-once quota commit after the final chunk, and owned idempotent PWA ACK. Evidence is `tests/test_chat_delivery_boundary.py` plus the chat contract suites. This does not prove external Telegram, PWA browser, AI, YooKassa, sandbox or production behavior.

## Acceptance boundary

- Current committed local code evidence относится к `main` / `b70d6ccf8bbeac49b77015be09295a41060fc9bd`: targeted tests — `147 passed`; focused PostgreSQL race coverage — `3 passed`; safe suite — `1081 passed`, `22 skipped`, `1 deselected`, `0 failed`; Ruff — PASS; independent review — no actionable findings.
- Более ранний [dated readiness review](../acceptance/evidence/telegram-first-v1-readiness-review.md) сохраняет собственный baseline `1059 passed`, `22 skipped`, `1 deselected`, `0 failed`; это число не обновляется задним числом и не приписывается commit `b70d6cc`.
- [External sandbox runbook](../acceptance/telegram-first-sandbox.md) — `RUNBOOK — NOT EXECUTION PROOF`. Внешние Telegram, YooKassa и AI/provider sandbox не выполнялись.
- `READY` означает локально подтверждённый implementation contract для конкретной строки. Он не означает launch approval, external sandbox PASS, production deployment, production availability или legal/policy readiness.
- Production и legal/policy readiness не доказаны; tracked Compose/deployment instructions не являются production evidence.

## Ключевые implementation gaps NURA 1.0

1. Durable delivery retry/progress для Free-chat и client ACK для web-chat до полного delivery-aware quota contract.
2. Внешняя Telegram/content acceptance полного отчёта text + PDF.
3. Минимальный persisted broadcast/campaign delivery, opt-out и analytics contract.
4. Канонический runtime style layer отдельно для report и chat consumers.
5. Migration disposition legacy 390/recurring.
6. Внешняя Telegram/YooKassa sandbox и production/legal/infrastructure acceptance.

## Правило обновления

Обновляй эту матрицу только после проверки фактического code/test/config evidence. Product target меняется только через отдельную задачу на каноническую спецификацию; roadmap checkbox или исторический документ не доказывает реализацию.
