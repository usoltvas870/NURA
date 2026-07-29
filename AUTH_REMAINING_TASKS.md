# NURA Authentication — Historical Remaining-Tasks Record

> **STATUS: HISTORICAL / SUPERSEDED AUTH CHECKLIST**
>
> Этот файл сохраняет историю PWA/email/VK auth-работ 1–2 июля 2026 года. Он не является current backlog, auth roadmap, production evidence или основанием для продления legacy-поддержки.

## 1. Authority and historical scope

Текущий продуктовый target задаёт [каноническая спецификация](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md), а фактическую реализацию подтверждают code/tests и её компактное [current-status mirror](docs/implementation/current-status.md). Telegram — основной identity path; guest/email/VK routes относятся к `LEGACY COMPATIBILITY` существующего web/PWA-клиента.

Этот документ возник как remaining-tasks checklist к прежнему [PWA auth implementation plan](docs/archive/legacy-pwa/architecture/auth-system-implementation-plan.md). Формулировки «срочно», «до деплоя», «что осталось сделать» и будущие product ideas отражали состояние на дату записи и больше не управляют разработкой.

## 2. Original baseline

Историческая запись была создана после auth-работ 1 июля 2026 года и затем обновлялась как смешанный список реализации и внешних действий.

| Исторический блок | Что фиксировал checklist | Как его следует читать сейчас |
|---|---|---|
| Guest profile | Создание временного профиля, merge и cleanup | Milestone, позднее подтверждённый current code/tests |
| Email magic link | Переход от Unisender к SMTP, отправка и verify | Partial milestone: service verify/merge exists, but production redirect cookie wiring has an implementation gap |
| VK ID | OAuth/provider flow, callback и guest merge | Milestone web compatibility; внешняя настройка VK не доказана этим файлом |
| SMS | Первоначальный план и последующая отмена | `HISTORICAL / SUPERSEDED`; SMS auth не является current path |
| Telegram linking | Связь web identity с Telegram | Current compatibility имеет отдельный `link_*` path; прежний `tgauth_*` flow retired |
| VPS/configuration | Миграция, credentials и deployment notes | Dated operator claims, не current production evidence |
| Product ideas | Retention email, segmentation, analytics, premium offers | Historical ideas, not part of committed roadmap |

Git chronology preserves the context: `2f753a6` introduced the original auth phases, and `ff9decd` updated this checklist after later VK/email/Celery fixes. Commit presence proves repository history, not deployment or provider acceptance.

## 3. Tasks that were implemented

`CURRENT — IMPLEMENTED` below means reachable local code with static test evidence; it does not mean current production availability. Explicit gaps remain gaps even when the underlying service method exists.

- Guest creation/fetch/conversion/merge routes are registered under `/api/v1/auth/*`; guest data is stored through the auth service/repositories and cached in Redis.
- Email magic-link send and verify routes are registered. `AuthService.verify_magic_link()` consumes the token, verifies the user and can merge guest data. The production route then calls `set_session_cookie()` on the injected `Response` but returns a different `RedirectResponse`; static inspection therefore indicates that the session cookie is not carried by the returned redirect. This is an `IMPLEMENTATION GAP`, not a working login claim. Existing email contract coverage exercises a fake E2E endpoint and service behavior, not this production route wiring.
- VK token authentication is registered at `POST /api/v1/auth/vk`. The service verifies provider identity, creates/reuses or links a user, merges guest data only after identity resolution and rejects conflicting or ambiguous identities. Provider calls are mocked in local tests.
- The web compatibility API can generate a Telegram `link_*` deep link for an authenticated web user.
- Auth routes have explicit per-route rate limits.
- Expired guest cleanup is registered as a daily Celery Beat task.
- The obsolete Telegram `tgauth_*` web endpoints and bot deep links are guarded as stateless retired flows returning a safe tombstone; tests verify that they do not access Redis or repositories.
- SMS authentication was removed from the active route contract. Historical Unisender/SMS setup steps therefore are not current work items.

The accepted [bot specification](docs/bot-spec.md) and [bot UX map](docs/bot-ux-map.md) classify guest/email/VK auth as `LEGACY COMPATIBILITY`, not Telegram-first onboarding.

## 4. Tasks that remain only as legacy compatibility questions

The following are not imperative tasks from this checklist:

- how long the legacy PWA and guest/email/VK identity paths remain supported;
- what deprecation notice and exit UX those paths require;
- whether a future compatibility release must re-run VK/email provider acceptance;
- whether the existing web-to-Telegram `link_*` path remains part of the eventual compatibility boundary.

These questions must be resolved against DM-03 and current repository evidence. The historical checklist does not choose a retirement date, provider rollout or support promise.

Separately, the email redirect/cookie defect above is a current `IMPLEMENTATION GAP`, not an owner decision or a legacy-support-duration question. Fixing it requires a separately authorized code/test session.

## 5. Superseded or unverifiable statements

- Claims that a migration, SMTP password, VK credentials, Celery Beat or email transport were configured on a VPS were point-in-time operator notes. This session performed no SSH, sandbox or production verification, so those claims are not current evidence.
- The old requirement to add `UNISENDER_API_KEY` conflicts with the same record's later SMTP transition and is superseded.
- The SMS.ru setup and Email-vs-SMS experiment were cancelled and do not belong to the current auth contract.
- The OneTap/callback descriptions mixed multiple integration variants. Current behavior must be read from `api/routes/auth.py`, `core/services/auth.py`, PWA code and tests.
- Statements such as «работает после настройки приложения», «проверено» or «развёрнуто» are retained only as historical assertions and must not be promoted to production acceptance.
- Referral rewards, retention mailings, segmentation, premium consultations and analytics were ideas in the old checklist. They are not accepted by this file and are not part of a committed auth roadmap.

## 6. Current authoritative destinations

| Question | Authority |
|---|---|
| What is the NURA 1.0/1.5 identity and PWA target? | [Canonical product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md) |
| What auth/PWA behavior is currently mirrored as implemented? | [Current implementation status](docs/implementation/current-status.md) plus code/tests |
| Why is PWA compatibility retained without a deadline? | DM-03 in [migration decisions](docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) |
| How does current Telegram onboarding differ from web compatibility? | [Bot specification](docs/bot-spec.md) and [bot UX map](docs/bot-ux-map.md) |
| Where is the original PWA auth plan? | [Legacy PWA auth plan](docs/archive/legacy-pwa/architecture/auth-system-implementation-plan.md) |
| Where is local/external/production evidence separated? | [Acceptance index](docs/acceptance/README.md) |

## 7. Owner decisions still pending

- `OWNER DECISION PENDING` — duration and retirement policy for legacy PWA plus guest/email/VK auth compatibility.

External provider, sandbox and production availability remain an `EVIDENCE BOUNDARY`, not an owner decision inferred by this file.

Telegram-first, retirement of `tgauth_*`, and classification of guest/email/VK as legacy compatibility are not pending in this document.

## 8. References

- [Documentation authority router](docs/README.md)
- [Canonical NURA 1.0/1.5 product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](docs/implementation/current-status.md)
- [Migration decisions](docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Migration file map](docs/reconciliation/2026-07-28/MIGRATION_FILE_MAP.md)
- [Current bot specification](docs/bot-spec.md)
- [Current bot UX map](docs/bot-ux-map.md)
- [Legacy PWA archive](docs/archive/legacy-pwa/README.md)
- `nura_app/api/routes/auth.py`
- `nura_app/core/services/auth.py`
- `nura_app/tests/test_auth.py`
- `nura_app/tests/test_email_auth_contract.py`
- `nura_app/tests/test_vk_auth_contract.py`
- `nura_app/tests/test_legacy_telegram_auth_retired.py`
