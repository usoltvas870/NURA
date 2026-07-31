# NURA: текущее состояние реализации

## Локальный fail-closed external sandbox milestone (2026-07-31)

На clean baseline `main` / `0be905226eebc1148d26bf89559d2ae5ce45096f`
реализован незакоммиченный отдельный профиль `APP_ENV=sandbox`: единые startup
gates API/bot/worker/Beat, проверка фактического Alembic head, global Telegram
allowlist, отдельные YooKassa provider-test и internal-shortcut contracts,
Redis-backed AI budget, isolated full-stack Compose, минимальный ingress и
offline preflight. После независимого review дополнительно закрыты legacy
YooKassa SDK bypass, host-level AI/resource identity checks, inline Redis
credentials, production URL markup и executable ASGI ingress enforcement.
Подробный контракт:
[external-sandbox-profile.md](../external-sandbox-profile.md).

Это локальное implementation evidence. External identity checks, provider calls,
Compose execution, DNS/TLS, migration apply, deploy, commit, push и PR не
выполнялись; внешний sandbox остаётся `NOT_EXECUTED`.

**Статус:** CURRENT IMPLEMENTATION MIRROR — EVIDENCE-BACKED, NON-NORMATIVE
**Проверено:** 2026-07-30
**Baseline:** локальный непубликовавшийся worktree на branch `main`, исходный HEAD `a6ef95e437e974f13ab78af15da612ac91c91f67`
**Назначение:** кратко отвечать на вопрос «что фактически реализовано сейчас» по коду, миграциям, конфигурации и тестам.

Этот документ не определяет product scope и не заменяет [каноническую спецификацию](../product/NURA_1_0_1_5_PRODUCT_SPEC.md). Расхождение с target называется implementation gap. Текущая запись отражает локальный write-session поверх указанного clean baseline; commit, push, PR, deploy и внешняя sandbox-проверка не выполнялись. Broadcast contour подтверждается focused unit/contract tests и disposable PostgreSQL concurrency/migration evidence; итоговый общий test count фиксируется в handoff этой сессии после полного validation gate. Статус `READY` означает наличие локально подтверждённой реализации и не означает sandbox или production readiness.

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
| Broadcasts | `READY (local)` | 1.0 | `nura_app/core/services/broadcast.py`, `nura_app/core/repositories/broadcast.py`, `nura_app/api/routes/admin_api.py`, `nura_app/bot/handlers/broadcast.py`, `nura_app/tests/test_broadcast_campaign.py`, `nura_app/tests/test_broadcast_admin_api.py` | Persisted campaign/delivery/audit/click/suppression, five canonical segments, estimate, exact-version test→launch, opt-out, frequency cap, bounded retry and last-click paid-order attribution реализованы; внешний Telegram sandbox и production operator access не проверялись | нет | оператор через Admin API; получатель через Telegram settings/CTA |
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
| Runtime prompts | `READY (local)` | 1.0 | `nura_app/core/prompts/runtime/`, resolver и metadata-aware consumers | Report/chat bundles разделены, version/hash/pinning/provenance проверяются; external content acceptance не выполнена | нет | опосредованно |
| Product analytics | `PARTIAL` | 1.0 | `nura_app/core/services/attribution.py`, `nura_app/core/services/broadcast.py`, `AttributionLink`/`AttributionTouch`, `BroadcastCTAClick`, attribution/broadcast tests | Acquisition attribution и campaign delivery/click/last-click paid-order metrics есть; единого event registry и полного KPI funnel для всех доменов нет | нет | нет |
| Support/admin | `READY` | operations | `nura_app/api/routes/admin_api.py`, `nura_app/admin_bot/` | Часть операций subscription-centric; production access/permissions отдельно не проверялись | нет | только operator/admin |
| External sandbox | `NOT_EXECUTED` | release gate | [acceptance evidence router](../acceptance/README.md), local acceptance tools и [external sandbox runbook](../acceptance/telegram-first-sandbox.md) | Telegram test bot, YooKassa test shop, external AI/provider, HTTPS and legal/support evidence отсутствуют | не применимо | нет |

## Local chat-delivery update (2026-07-30)

`READY` locally for the narrow free-chat delivery contract: durable Telegram multipart progress/retry, terminal release, exactly-once quota commit after the final chunk, and owned idempotent PWA ACK. Evidence is `tests/test_chat_delivery_boundary.py` plus the chat contract suites. This does not prove external Telegram, PWA browser, AI, YooKassa, sandbox or production behavior.

## Local broadcast-campaign update (2026-07-30)

`READY (local)` for the NURA 1.0 minimal manual Telegram campaign contour. Campaign content and CTA destinations are validated and versioned; estimate and test-send are pinned to the launch version; launch materializes a bounded recipient snapshot and is idempotent; delivery attempts are fenced and persist partial media/text progress; opt-out, blocked-user suppression, frequency cap, clicks, audit and bounded last-click paid-order attribution are durable. The old direct broadcast endpoint/task fail closed, and legacy editorial/NURA 1.5 beat jobs are absent from the default schedule. This does not prove an external Telegram send, operator production permissions or product/legal approval of any content.

## Local prompt-governance update (2026-07-31)

`READY (local)`: active mini/full/kitchen report generation и free chat используют independent checked-in `report/v1` и `chat/v1` bundles с canonical manifests, strict inventory/SHA-256/placeholders, allowlisted resolver, explicit config versions и fail-closed boot validation. Nullable bounded JSONB provenance сохраняется для новых report/mini/chat outputs; legacy rows не получают ложную v1 attribution. Full/mini retry pinned к durable generation record, chat replay/delivery — к persisted response. Подробный контракт: [prompt governance](../prompt-governance.md). External AI content acceptance не выполнялась.

## Acceptance boundary

- Current local broadcast evidence относится к непубликовавшемуся worktree поверх `main` / `a6ef95e437e974f13ab78af15da612ac91c91f67`; итоговые counts и independent review перечисляются в handoff этой write-session, а не приписываются исходному commit.
- Более ранний [dated readiness review](../acceptance/evidence/telegram-first-v1-readiness-review.md) сохраняет собственный baseline `1059 passed`, `22 skipped`, `1 deselected`, `0 failed`; это число не обновляется задним числом и не приписывается commit `b70d6cc`.
- [External sandbox runbook](../acceptance/telegram-first-sandbox.md) — `RUNBOOK — NOT EXECUTION PROOF`. Внешние Telegram, YooKassa и AI/provider sandbox не выполнялись.
- `READY` означает локально подтверждённый implementation contract для конкретной строки. Он не означает launch approval, external sandbox PASS, production deployment, production availability или legal/policy readiness.
- Production и legal/policy readiness не доказаны; tracked Compose/deployment instructions не являются production evidence.

## Ключевые implementation gaps NURA 1.0

1. Durable delivery retry/progress для Free-chat и client ACK для web-chat до полного delivery-aware quota contract.
2. Внешняя Telegram/content acceptance полного отчёта text + PDF.
3. External report/chat content acceptance и вторая approved bundle version для config-only rollback.
4. Migration disposition legacy 390/recurring вне закрытого broadcast beat bypass.
5. Внешняя Telegram/YooKassa sandbox и production/legal/infrastructure acceptance.

## Правило обновления

Обновляй эту матрицу только после проверки фактического code/test/config evidence. Product target меняется только через отдельную задачу на каноническую спецификацию; roadmap checkbox или исторический документ не доказывает реализацию.
