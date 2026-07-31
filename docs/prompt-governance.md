# NURA runtime prompt governance

**STATUS: CURRENT TECHNICAL CONTRACT — LOCAL IMPLEMENTATION**

Этот документ описывает проверяемый runtime-контракт prompt bundles. Canonical product target остаётся в [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md), а prompt bodies находятся только в `nura_app/core/prompts/`.

## 1. Граница

Governance распространяется на `report.mini`, `report.full`, `report.kitchen` и `chat.free`. Report и chat имеют независимые checked-in bundles:

- `core/prompts/runtime/report/v1`;
- `core/prompts/runtime/chat/v1`.

Daily Card, compatibility и expanded Tarot не используют active report/chat defaults. Их существующие prompt paths остаются отдельными; compatibility и expanded Tarot сохраняют false-by-default feature boundaries NURA 1.0.

## 2. Focused inventory до milestone

| Consumer | Старый runtime contract | Output | Persisted metadata | Gap / classification |
|---|---|---|---|---|
| Mini report | shared cached `system_prompt.txt` + `cot_instruction.txt` + `mini_analysis.txt` | `MiniAnalysisResult` | отсутствовала | active NURA 1.0; shared system, implicit placeholders, no hash |
| Full report | shared cached system/reasoning + part A/B | `FullReportResult` | отсутствовала | active NURA 1.0; retry мог заново читать active files, unsafe instructions |
| Kitchen component | shared cached system/reasoning + `kitchen_report.txt` | `KitchenReportResult` | отсутствовала | user-visible through full report; same coupling |
| Free chat | separately cached `chat_system_prompt.txt` | text | response only | active NURA 1.0; no version/hash/provider provenance |
| Daily Card | own Tarot/daily prompts | feature-specific | feature-specific | active separate consumer; outside bundle defaults |
| Compatibility / expanded Tarot | feature-specific prompts, some legacy `_system_prompt()` calls | feature-specific schemas | feature-specific | legacy/1.5; isolated from new defaults, feature flags remain false by default |

Legacy `_system_prompt()` и `_load_prompt()` сохранены только для не мигрированных legacy/1.5 consumers. Active mini/full/kitchen и free chat разрешают bundle через registry.

## 3. Manifest и resolver

Каждый canonical JSON manifest фиксирует bundle id/version, style/output-schema versions, status, sorted allowed consumers, strict file inventory, SHA-256 и exact required placeholders. Resolver:

- принимает только code-allowlisted consumer + version;
- запрещает absolute, traversal и backslash paths;
- проверяет canonical JSON, manifest schema, approval status, inventory, UTF-8, non-empty content, SHA-256 и exact placeholders;
- возвращает immutable bundle и aggregate SHA-256;
- не обращается к сети, Redis или БД и не принимает admin/user paths.

Изменение prompt file без manifest hash update fail closed. Изменение manifest/content внутри уже pinned version с другим aggregate hash также не может продолжить существующий job.

## 4. Active versions и rollback

`REPORT_PROMPT_BUNDLE_VERSION` и `CHAT_PROMPT_BUNDLE_VERSION` имеют default `v1`. API import/boot и Telegram startup валидируют active bundles; relevant consumer повторяет resolution. Unknown, malformed или unapproved version не получает empty/global fallback.

В репозитории пока одна approved version. Поэтому prompt rollback означает application/git deploy rollback целиком. Когда появится вторая проверенная version, rollback выполняется только config/deploy selection на checked-in approved bundle. Исторические outputs не перегенерируются.

## 5. Content contracts

Report system, style и internal reasoning checklist разделены. Checklist не требует раскрывать chain of thought и требует grounding, schema consistency и проверку forbidden claims. Required legacy keys `life_forecast`, `health_analysis`, `psychological_blocks`, `ancestral_programs` и другие сохранены ради renderer/resend compatibility, но active prompt задаёт safe semantic mapping без прогнозов, органов/заболеваний/чакр, диагнозов и выдуманной истории рода.

Chat contract честно оставляет NURA AI, не заявляет личное знакомство, не требует Matrix reference или вопрос в конце каждого ответа, не пересчитывает Matrix из сообщения и рассматривает user/history как данные, а не system policy. Existing crisis/safety disposition и quota/delivery flow не заменяются.

## 6. Execution metadata и pinning

Nullable bounded JSONB `generation_metadata` добавлен к `reports`, `mini_report_generations` и `chat_message_usages`. Legacy rows остаются `NULL`; backfill в `v1` запрещён.

Metadata содержит consumer, bundle id/version/hash, style/output-schema versions, requested provider/model, фактические provider/model или `null`, `generation_source`, UTC generated_at и SHA-256 structured/context input. Raw system prompt, birth date, conversation/report content, headers, credentials и chain of thought не сохраняются.

Full report pin записывается атомарно с durable generation claim; semantic retry, part A/B и kitchen используют один resolved bundle. Mini retry использует pin generation row. Chat pin сохраняется в reservation, а final metadata — атомарно с `result_ready`. Delivery retry/replay использует persisted response и не вызывает модель.

## 7. Fallback и cache

Schema-shaped report fallbacks прямо обозначают технический fallback и не изображают provider-generated персональный анализ. У них `generation_source=fallback`, а successful provider/model не выдумываются. Chat fallback освобождает reservation и не расходует quota.

AI cache key по-прежнему зависит от exact messages/model/params; version/hash влияют через resolved system content. Cache payload хранит bounded completion metadata, не raw logs. Разные bundle contents не разделяют key.

## 8. Human review и external boundary

Sanitized packet без model invocation:

```powershell
cd nura_app
$env:APP_ENV='test'
python tools/build_prompt_review_packet.py --output <controlled-output-path>
```

Packet содержит fixture/scenario id, consumer, bundle version/hash, schema/style versions и checklist; prompt text, birth dates, secrets и user content отсутствуют. Это локальный review mechanism, не external content acceptance.

External AI/provider sandbox остаётся `NOT EXECUTED` и требует отдельного approval/evidence. Remote prompt CMS, editor, DB/Redis editable prompt, hot reload, A/B allocation и новый provider отсутствуют.

## 9. Post-1.0 follow-up

Владелец принял два non-blocking residual risk без исправления в текущем milestone: full-report retry закрепляет prompt bundle version/hash, но requested model может измениться при config/deploy change между попытками; JSON repair telemetry пока не агрегирует usage/duration repair-запроса в первоначальную completion statistic. Оба пункта остаются post-1.0 follow-up и не являются закрытыми возможностями.

## 10. Migration и privacy

Alembic `d8e9f0a1b2c3` — additive nullable migration поверх `c6d7e8f9a0b1`, с downgrade удалением трёх columns. Account deletion удаляет metadata вместе с owned report/mini/chat rows по существующим delete/CASCADE boundaries. Production migration в implementation-сессии не применялась.
