# NURA: решения владельца, необходимые после Этапа 1

**STATUS: DATED QUESTION SET — RESOLVED ITEMS DEFER TO `docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md`**

Ниже только вопросы, на которые нет однозначного ответа в canonical spec, коде и действующих документах. Уже принятые решения (Telegram-first, 890 ₽, YooKassa only, no Stars, 399 ₽/30 дней в 1.5, no auto-renew baseline, no public channel) не повторяются как вопросы.

| ID | Когда нужно | Решение | Варианты/последствия |
|---|---|---|---|
| OD-01 | RESOLVED by DM-CHAT-DAILY | Как сбрасываются 5 бесплатных сообщений? | 5 успешных ответов за продуктовый день, 00:00 `Europe/Moscow`, без переноса остатка; единая Telegram/legacy-PWA квота. |
| OD-02 | До выключения legacy monetization | Что делать с существующими/возможными пользователями 390 ₽ subscription/Tarot и saved payment methods? | Hide for new users + honor until expiry; immediate retirement; migration credit. Нужны правила cancellation/refund/data retention. |
| OD-03 | До очистки 1.0 bot menu | Какие уже реализованные 1.5-функции видимы в 1.0: expanded Tarot, compatibility, referrals? | Скрыть feature flags; оставить без promotion; включить как beta. Нельзя позволить им блокировать core funnel. |
| OD-04 | До изменения web routes | Каков обязательный срок/режим обратной совместимости PWA, email/VK auth и web report links? | Read-only compatibility, time-boxed sunset или поддерживаемый secondary client. Нужны migration/redirect rules. |
| OD-05 | До implementation NURA 1.5 | Получают ли ранние покупатели 1.0 30-day gift и от какой даты? | Canonical §42 оставляет migration rule открытым. |
| OD-06 | До 1.5 Tarot persistence | Сколько хранить историю раскладов и какие типы входят в accepted set? | Влияет на модель `TarotReading`, privacy, cost и «Мои материалы». |
| OD-07 | До 1.5 expanded chat | Fair-use thresholds и пользовательское обещание. | Нужны rate/cost limits без ложного «безлимита». |
| OD-08 | До broadcast rollout | Quiet hours, timezone fallback, frequency cap и окно атрибуции CTA. | Влияет на scheduling, suppression, campaign analytics и trust. |
| OD-09 | До NURA 1.5B | Referral reward, self-referral/anti-fraud и цена/включение compatibility. | Canonical фиксирует только область, не параметры. |
| OD-10 | До финального documentation migration | Каноническое место для generic OpenCode agent files: root `.opencode/` или `nura_app/.opencode/`? | 11 точных дублей; выбор нужен, чтобы безопасно удалить/заменить копии на индекс. |
| OD-11 | До архива research | Нужны ли video assembler и NURA Forms как активные NURA subsystems или как future content tooling? | Код video assembler существует; product roadmap не определяет его обязательность. |
| OD-12 | До принятия runtime style layer | Где хранить утверждённый `NURA_RUNTIME_SYSTEM_PROMPT.md` и кто принимает content version? | Canonical требует файл, но repository rule требует AI prompts только в `core/prompts/`; нужен единый путь без двух sources of truth. |

## Не являются owner decisions

- Исправление отсутствующих ссылок `bot-spec-audit.md`, `docs-plan.md`, `image-prompts.md` — техническая cleanup-задача Этапа 2.
- Перенос явно PWA-first документов в legacy — информационная миграция, не пересмотр product pivot.
- Отсутствие full-report text delivery, broadcast persistence и runtime prompt integration — implementation gaps.
- Production/sandbox verification — отдельная acceptance-задача с разрешением, а не product decision.
