# NURA Runtime Prompt Contracts

## 1. Authority and scope

Документ инвентаризирует runtime-reachable report/chat prompt files, loaders, consumers, inputs, outputs, validation и acceptance status. Он не копирует prompt bodies и не заменяет canonical [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md).

Current behavior подтверждается reachable code в `nura_app/core/services/`, файлами `nura_app/core/prompts/`, schemas, configuration и tests. Product spec задаёт target separation report/chat contracts, но не доказывает release/version governance.

Commercial access, chat quota и Telegram UX остаются в [bot-spec.md](bot-spec.md), [bot-ux-map.md](bot-ux-map.md), [pricing.md](pricing.md).

## 2. Status legend

- `CURRENT — IMPLEMENTED` — prompt загружается reachable consumer и влияет на runtime.
- `TARGET — NURA 1.0` — утверждённый target contract, не выводимый из file presence.
- `TARGET — NURA 1.5` — later product prompt boundary.
- `IMPLEMENTATION GAP` — обязательная governance/behavior не подтверждена evidence.
- `LEGACY COMPATIBILITY` — prompt/consumer сохранён для старой supported surface.
- `HISTORICAL / SUPERSEDED` — unconsumed/obsolete/provenance-only prompt material.
- `OWNER DECISION PENDING` — нерешённая acceptance/provider/rollout policy.
- `EVIDENCE BOUNDARY` — repository evidence не доказывает external runtime/content quality.
- `OUT OF SCOPE` — editorial или иная prompt system вне current report/chat contracts.

## 3. Current prompt registry

Все пути ниже находятся в `nura_app/core/prompts/`. File presence недостаточно: registry требует reachable loader/consumer либо явную classification.

| Contract role | Exact file | Loader/consumer | Runtime output | Classification |
|---|---|---|---|---|
| Shared non-chat system instruction | `system_prompt.txt` | module-level `nura_app.core.services.ai._system_prompt()`; mini/full/kitchen, compatibility, Tarot weekly/question/mini-spread | System message нескольких AI features | `CURRENT — IMPLEMENTED`, cross-feature coupling |
| Shared reasoning instruction | `cot_instruction.txt` | `_load_prompt()`; interpolation в mini/full/kitchen templates | Instruction fragment | `CURRENT — IMPLEMENTED` |
| Mini narrative | `mini_analysis.txt` | `AIService.generate_mini_analysis()` | `MiniAnalysisResult` | `CURRENT — IMPLEMENTED` |
| Full narrative, part A | `full_report_part_a.txt` | `AIService.generate_full_report()` через `ReportGenerationLoop` | Первая часть `FullReportResult` | `CURRENT — IMPLEMENTED` |
| Full narrative, part B | `full_report_part_b.txt` | тот же consumer/loop | Остальные поля, merge в `FullReportResult` | `CURRENT — IMPLEMENTED` |
| Kitchen narrative | `kitchen_report.txt` | `AIService.generate_kitchen_report()` | `KitchenReportResult` | `CURRENT — IMPLEMENTED` |
| Chat system instruction | `chat_system_prompt.txt` | `_chat_system_prompt_template()` → `_build_chat_system_prompt()` → `chat_response()` | System context для plain-text chat | `CURRENT — IMPLEMENTED` |
| Old monolithic full prompt | `full_report.txt` | Current Python consumer не найден | Нет output в current pipeline | `HISTORICAL / SUPERSEDED` |

Compatibility, Tarot, quiz, admin/editorial и прочие feature-specific prompts не добавляются автоматически к двум contracts. Однако shared `system_prompt.txt` реально используется report, compatibility и несколькими Tarot consumers: изменение этого файла имеет cross-feature impact, даже если feature-specific contracts остаются `OUT OF SCOPE`.

## 4. Report generation contract

### Inputs — `CURRENT — IMPLEMENTED`

Report consumer получает validated identity/date context и serialized deterministic `MatrixData`. Он объединяет их с shared system/reasoning instructions. Mini получает matrix/reasoning; full parts также получают name/birth date; kitchen — matrix/reasoning.

AI layer повествует по supplied structure, но не является authority для matrix calculation, order entitlement, lifecycle state, artifact integrity или delivery.

### Outputs — `CURRENT — IMPLEMENTED`

- Mini: JSON по `MiniAnalysisResult`.
- Full: два последовательных JSON objects, merge и validation `FullReportResult`.
- Kitchen: JSON по `KitchenReportResult`.

Full report loop применяет `ContentVerifier` и до двух regeneration retries после первой attempt. После исчерпания semantic acceptance возвращается defined full fallback. Mini application не считает generic mini fallback successful generation.

### Model call — `CURRENT — IMPLEMENTED`

Client использует DeepSeek-compatible base URL, API key и model из `core/config.py`; current default — `deepseek-chat`. Report calls используют report parameter set, kitchen переопределяет temperature/max tokens. Низкоуровневый provider call в `AIService.chat()` имеет bounded retry/fallback sequence.

### `EVIDENCE BOUNDARY`

Shared non-chat system prompt и report task files образуют reachable composite implementation, а не единый independently released report-contract artifact. Между ними есть фактический conflict: system instruction запрещает отдельные chakra/karmic/prediction frames, тогда как full part/reasoning files требуют health/chakra/psychosomatic и multi-year prediction-like material. Schema validation и selected semantic checks не разрешают этот conflict и не доказывают factual/safety correctness narrative.

## 5. NURA chat contract

### `CURRENT — IMPLEMENTED`

`chat_system_prompt.txt` загружается и кэшируется отдельно от report system instruction. `_build_chat_system_prompt()` подставляет user name, archetype name/number/key и serialized matrix context. `chat_response()` добавляет не более последних десяти history entries и current user message и запрашивает plain-text answer с chat-specific parameters.

Chat consumer не генерирует report: не возвращает `FullReportResult`, не рендерит report templates, не сохраняет artifact и не определяет paid entitlement. Его output — conversational text для chat application.

Current chat tests подтверждают более узкую boundary: отказ анализировать другого человека и запрет пересчитывать matrix. Отдельного test evidence для medical/diagnostic/future-prediction behavior в просмотренных chat tests нет. Здесь target safety boundary описан без приписывания tests отсутствующих assertions.

Chat access/quota/gating — `OUT OF SCOPE`; authority находится в accepted bot docs.

## 6. Structured truth and safety boundary

### `TARGET — NURA 1.0` and current invariant

Runtime voice может стать естественнее без изменения deterministic/factual content. Вне stylistic authority остаются:

- matrix calculations/positions;
- approved arcana facts и structured report fields;
- schemas/serialization contracts;
- payment/refund/ownership/lifecycle facts;
- medical/psychological diagnosis boundaries;
- objective prediction claims и safety rules;
- deterministic report structure downstream consumers.

NURA не должна описываться как therapist, oracle, diagnostic system или objective future predictor. Model объясняет supplied symbolic material, но не создаёт новый calculation truth layer.

### `EVIDENCE BOUNDARY`

Prompt instructions влияют на model behavior, но не равны deterministic enforcement. Pydantic отклоняет malformed structure; `ContentVerifier` покрывает только selected semantic properties. Safety/factual acceptance требует tests/evaluation criteria сверх prompt prose.

## 7. Loading and consumers

### Loader behavior — `CURRENT — IMPLEMENTED`

Module-level `PROMPTS_DIR` указывает на `core/prompts`. `AIService._load_prompt(name)` читает UTF-8 и возвращает empty string, если file отсутствует. `_system_prompt()` и `_chat_system_prompt_template()` независимо кэшируют соответствующие files.

Silent empty-string означает отсутствие fail-fast configuration error: formatting/provider может отказать позже либо работать без intended instruction. Это `IMPLEMENTATION GAP` explicit prompt-contract loading.

### Interpolation — `CURRENT — IMPLEMENTED`

- Task templates используют Python `str.format()` с named placeholders.
- Mini/full/kitchen получают loaded reasoning string и serialized matrix data.
- Full part templates также получают identity/date fields.
- Chat получает formatted archetype/user/matrix context; history/messages передаются отдельными chat messages.

Interpolation single-pass: placeholders внутри уже подставленного `cot_instruction.txt` повторно не форматируются. В текущем reasoning file есть `{name}`, поэтому этот token остаётся literal даже в full path, где outer template получает `name`; mini/kitchen consumer имя в outer `.format()` вообще не передаёт. Placeholder compatibility между files и consumer arguments — часть effective runtime contract, хотя formal metadata registry её не объявляет.

### Consumer boundary

- Report: `generate_mini_analysis()`, `generate_full_report()`, `generate_kitchen_report()` в `core/services/ai.py`; full также обёрнут `core/loop_specs/report_loop.py`.
- Chat: `chat_response()` в `core/services/ai.py`, вызываемый chat application/service path.
- Shared non-chat system consumer coupling: compatibility generation и Tarot weekly/question/mini-spread также вызывают `_system_prompt()`; их task prompts/schemas остаются вне report/chat registry, но обязаны учитываться при изменении shared file.
- `full_report.txt` не имеет current Python consumer и не является active report prompt.

## 8. Output parsing and validation

### Report JSON — `CURRENT — IMPLEMENTED`

`_parse_json_response()` последовательно пробует:

1. direct JSON decoding;
2. JSON из fenced block;
3. один corrective provider call для valid JSON;
4. `ValueError`, если parsing не удался.

Parsed objects валидируются Pydantic result models. Full parts A/B merge-ятся до `FullReportResult` validation. Part-A exception даёт full fallback; part-B exception логируется, а merged schema validation определяет наличие complete result.

### Chat text — `CURRENT — IMPLEMENTED`

Chat output — plain text, не report schema. Provider/client failure после error handling возвращает configured chat fallback string.

### Failure semantics

- Mini errors дают `FALLBACK_MINI`; application записывает retryable generation failure.
- Full/kitchen определяют schema-shaped fallbacks; full semantic loop — terminal full fallback после bounded attempts.
- Provider calls ретраят transient errors с bounded backoff и затем surface-ят last error consumer-у, применяющему feature fallback.

Fallback — resilience behavior, не доказательство product content acceptance.

## 9. Versioning and acceptance status

### Current evidence

- Report/chat имеют separate files, cached loaders, consumers, context construction, output surfaces и parameter sets.
- Mini generation имеет lifecycle id `mini-v1`, но это idempotency version, не prompt hash/accepted prompt release.
- В reachable paths не найдены report/chat prompt version string, content hash, metadata manifest, bound changelog, environment selector, independent rollout или rollback registry.
- Tests покрывают loading/consumption, malformed JSON, schema parsing, узкий chat refusal/recalculation boundary, fallback и orchestration, но не formal golden acceptance suite двух independently released contracts и не полный medical/prediction safety contract.

`IMPLEMENTATION GAP — separate prompt files/consumers exist, but independently accepted and versioned runtime contracts are not yet established`

## 10. Target NURA 1.0

### `TARGET — NURA 1.0`

Canonical target требует independently versioned report/chat runtime contracts под `core/prompts/`. «Independent» означает не только разные filenames: каждому нужны identifiable accepted content, compatible inputs/outputs, evidence и controlled release/rollback без implicit изменения другого.

Report target поддерживает Telegram-first mini/full и сохраняет deterministic truth. Chat target сохраняет conversational/safety contract, не наследуя report formatting или commercial access rules.

Target gaps, не автоматически approved implementation tasks:

- prompt version identity и metadata/hash binding;
- separate acceptance fixtures/evaluation thresholds;
- compatibility checks placeholders/output schemas;
- independent rollout, environment selection, monitoring, rollback;
- binding accepted prompt version к generated artifacts/operational evidence, если owner-approved.

Acceptance thresholds, rollout policy и model/provider changes — `OWNER DECISION PENDING` без новой authority.

## 11. NURA 1.5 and future prompts

### `TARGET — NURA 1.5`

Gift, expanded Tarot и compatibility surfaces требуют approved runtime consumers, schemas, evidence и safety boundaries. Examples/planned prompt names в historical docs не создают contracts.

Future image/visual prompts, expanded report sets, compatibility rules и provider/model changes — `OWNER DECISION PENDING`. Runtime-reachable image-prompt step в current mini/full pipeline отсутствует.

`HISTORICAL / SUPERSEDED` examples объясняют provenance, но не становятся current files, roadmap или production contract.

## 12. Content Studio boundary

### `OUT OF SCOPE`

`NURA_CONTENT_STUDIO_PROJECT_GUIDE` — editorial guidance для content plans, scripts, dialogues, short videos, carousels, posts, covers, publication descriptions. Он не является automatic authority для:

- production report/chat prompts;
- API/engineering docs;
- matrix calculations/arcana facts;
- runtime schemas, safety contracts, acceptance criteria.

Runtime loader/consumer reference на guide в report/chat registry не найден. Его editorial rules не импортируются сюда; guide не production prompt source.

## 13. Change-control implications

Пока formal independent versioning отсутствует, изменение reachable prompt file — production behavior change. Review должен охватывать:

1. exact loader/placeholders;
2. consumer inputs/model parameters;
3. output schema/parser/fallbacks;
4. report template/delivery consumers и все compatibility/Tarot consumers shared `system_prompt.txt`;
5. safety/deterministic-truth constraints;
6. scoped tests и risk-proportionate external acceptance evidence.

Изменение prose без schema changes может сломать JSON, semantic verification, length, safety, token use или rendering. Изменение dormant `full_report.txt` не меняет current full generation без wiring change.

Model/provider, acceptance thresholds и rollout strategy требуют owner authority.

## 14. Implementation gaps

- `IMPLEMENTATION GAP` — нет independent version ids, hashes/metadata, acceptance registry, rollout, rollback, environment selection.
- `IMPLEMENTATION GAP` — missing prompt file даёт empty string вместо fail-fast contract/configuration error.
- `IMPLEMENTATION GAP` — placeholder compatibility implicit в `str.format()` и не проверяется registry/build-time contract check.
- `IMPLEMENTATION GAP` — `{name}` внутри inserted `cot_instruction.txt` не раскрывается из-за single-pass interpolation и уходит в current report prompts literal token.
- `IMPLEMENTATION GAP` — shared `system_prompt.txt` связан с report, compatibility и Tarot consumers, поэтому report system contract не изолирован как release unit.
- `IMPLEMENTATION GAP` — system и full/reasoning task prompts содержат противоположные chakra/karmic/prediction requirements; complete safety acceptance evidence отсутствует.
- `IMPLEMENTATION GAP` — local tests не устанавливают provider/sandbox/production content acceptance.
- `IMPLEMENTATION GAP` — full-report content есть в PDF, но current Telegram delivery не имеет approved full-text surface; prompt capability не закрывает delivery gap.
- `EVIDENCE BOUNDARY` — current semantic/safety checks покрывают selected cases, не все generative responses.

## 15. References

Документация:

- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Report system specification](report-spec.md)
- [Structured and narrative architecture](two-layer-architecture.md)
- [Current implementation status](implementation/current-status.md)
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Bot specification](bot-spec.md)

Runtime implementation:

- [AI service and loaders/consumers](../nura_app/core/services/ai.py)
- [Runtime prompt directory](../nura_app/core/prompts)
- [Fallbacks and model parameters](../nura_app/core/fallbacks.py)
- [Runtime result schemas](../nura_app/core/schemas/__init__.py)
- [Full report loop](../nura_app/core/loop_specs/report_loop.py)
- [Content verifier](../nura_app/core/services/verifier.py)
- [Runtime configuration](../nura_app/core/config.py)
