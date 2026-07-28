# Stage 2A execution report

**STATUS: PASS WITH GAPS — STRUCTURAL MIGRATION COMPLETE, CONTENT CONSOLIDATION DEFERRED**
**Date:** 2026-07-28
**Branch / HEAD:** `main` / `61977175ef3b88fad618674fca2554db60aae379`

## Выполнено

- Создан authority-first слой: canonical product spec, owner migration decisions, current implementation status и новый `docs/README.md` router.
- В product spec внесено только утверждённое решение по Free-чату: 5 успешно доставленных содержательных ответов каждый продуктовый день, 00:00–23:59 `Europe/Moscow`, без переноса остатка, с единой Telegram/legacy-PWA квотой и конфигурируемыми limit/timezone.
- Current implementation отделён от target: daily quota отмечена как implementation gap к существующему lifetime ledger; legacy 390/recurring, PWA, email/VK, Tarot, compatibility и referral не выданы за target 1.0.
- Current acceptance отделён от historical PWA checklist; local evidence не объявляет external/production readiness.
- Явные PWA-first документы перенесены в `docs/archive/legacy-pwa/` и получили status banners.
- Superseded agent/dev/router snapshots сохранены в `docs/archive/superseded/`.
- Future platform/content ideas отделены в `docs/vision/` со статусом `NOT COMMITTED TO ROADMAP`.
- Current standards/research/evidence перемещены в стабильные разделы.
- Все семь Stage 1 reconciliation reports сохранены в `docs/reconciliation/2026-07-28/`.
- Root и nested AGENTS получили компактную authority navigation; damaged mojibake snapshots сохранены в superseded archive.
- Mixed документы сохранены без массового переписывания и помечены для Stage 2B.

Полная per-file карта: [MIGRATION_FILE_MAP.md](MIGRATION_FILE_MAP.md).

## Итоговые категории затронутых артефактов

Категории ниже взаимоисключающие для 68 затронутых content/navigation artifacts; неизменённые assets и tool/generated files не пересчитывались.

| Итоговая категория | Файлов |
|---|---:|
| Canonical target product | 1 |
| Owner migration decision | 1 |
| Current implementation mirror | 1 |
| Current acceptance/evidence | 5 |
| Current technical/operations/standards/research | 8 |
| Legacy PWA archive | 12 |
| Superseded archive | 6 |
| Future vision | 2 |
| Mixed — Stage 2B pending | 15 |
| Reconciliation evidence/reports | 9 |
| Authority/section indexes and current agent navigation | 8 |
| **Всего** | **68** |

Исходная semantic inventory Stage 1 (180 artifacts) не переписывалась и остаётся dated evidence. Новые Stage 2A indexes/reports не следует механически добавлять к старым category counts без нового полного inventory audit.

## Авторитетные документы после Stage 2A

| Вопрос | Источник |
|---|---|
| Product target NURA 1.0/1.5 | `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md` |
| Current implemented state | code/migrations/tests/config; зеркало `docs/implementation/current-status.md` |
| Owner migration decisions | `docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md` |
| Documentation navigation | `docs/README.md` |
| Acceptance boundaries | `docs/acceptance/README.md` |
| Legacy PWA | `docs/archive/legacy-pwa/README.md` — compatibility/history only |
| Future platform vision | `docs/vision/platform-independent/README.md` — not roadmap |

`STATE.md`, research, archive, vision, reconciliation и mixed files не являются самостоятельными product contracts.

## Перенесённые решения владельца

- Telegram-first остаётся текущей моделью.
- Markdown product spec — единственный canonical target внутри repository docs.
- PWA сохраняется как legacy compatibility без установленного deprecation срока.
- 890 ₽ Full Matrix и YooKassa only — target 1.0; 390 recurring — legacy conflict, 399/30 days — только target 1.5.
- Runtime prompts остаются в `nura_app/core/prompts/`, не в документации.
- «Мои материалы» не блокируются чат-квотой.
- Отдельный Telegram-канал не является обязательным roadmap.
- Daily Free-chat contract окончательно фиксирует reset в 00:00 `Europe/Moscow` и закрывает прежний open parameter.

## Baseline и конфликты

- Worktree был dirty до Stage 2A. Все Python/test/helper/runtime изменения сохранены без редактирования.
- `STATE.md` уже имел внешний незавершённый diff и не изменялся Stage 2A. Поэтому его исторические упоминания старых путей (`NURA_SITE_QA_AUDIT_2026-07-06.md` и другие) намеренно не переписывались.
- `docs/README.md` и `docs/launch-checklist.md` имели внешний documentation diff. Он не потерян: старый README сохранён как superseded snapshot; launch checklist безопасно разделён по явной границе current/historical.
- Existing untracked sandbox/readiness docs и семь reconciliation reports перемещены с сохранением содержания и получили authority banners.
- Root research duplicates не идентичны repository copies, поэтому не объединялись. Они помечены как mixed/duplicate и оставлены для Stage 2B.
- Root PDF и docs PDF с раскладами byte-identical, но destructive/binary deduplication не выполнялась.

## Намеренно не выполнено

- Не выполнялся Stage 2B: не создавались полные Telegram/payments/reports/chat/broadcast architecture contracts.
- Mixed bot/pricing/report/prompt/Tarot/brand/payment documents не разделялись содержательно.
- Не проектировались feature flags и не скрывались legacy runtime surfaces — код менять запрещено.
- Не переносились три research PDFs: бинарный файл не может содержать требуемый Markdown status banner; router уже классифицирует их как non-normative. Нужна отдельная safe binary migration/index task.
- Не объединялись non-identical root/docs research duplicates.
- Не изменялись runtime prompts.
- Не выполнялись application tests, external sandbox, commit, push, PR или deploy.

## Ссылки и исключения

Активный Markdown link-check после перемещений не обнаруживает отсутствующих внутренних targets. Relative links в legacy PWA compatibility docs обновлены.

Исключение: `docs/archive/superseded/docs-README-pre-stage-2a.md` намеренно сохраняет ссылки старого router baseline, включая старые пути. Это archived snapshot, он исключён из active navigation и не должен исправляться как current документ. Остальные архивные documents получают ссылки на current authority через banners.

## Вопросы для Stage 2B

1. Разделить bot spec/UX на current Telegram architecture, target UX и legacy appendix.
2. Создать evidence-backed payments/entitlements contract: current 890, retirement 390/recurring, target 399/gift.
3. Консолидировать reports architecture и явно развести HTML render source, Telegram text и PDF delivery.
4. Описать daily chat quota migration/idempotency после реализации target reset policy.
5. Создать broadcasts/lifecycle и AI prompt architecture без переноса runtime prompts в docs.
6. Разделить Tarot/compatibility/referral early implementation и accepted 1.5 release scope.
7. Провести safe binary research migration/deduplication и решить non-identical root/docs research copies.
8. Обновить acceptance/operations content, не смешивая local evidence с external/production proof.
9. Повторно построить полный inventory, если нужны новые totals после добавления Stage 2A artifacts.

## Финальная валидация Stage 2A

- `git diff --check`: PASS, exit code 0.
- Strict UTF-8 decode: PASS для 73 текстовых documentation/AGENTS files.
- Trailing whitespace: PASS; 36 whitespace-only lines и один одиночный хвостовой пробел удалены, 29 намеренных Markdown hard breaks сохранены.
- Active internal Markdown links: PASS, проверено 178 локальных targets, broken/unparseable — 0/0; superseded router snapshot исключён как документированное архивное исключение.
- Canonical product spec uniqueness: PASS, внутри `docs/` найден ровно один `NURA_1_0_1_5_PRODUCT_SPEC.md`.
- Daily Free-chat contract: PASS по всем утверждённым условиям owner decision.
- Authority router: PASS; archive не объявлен текущим контрактом, vision не объявлен roadmap.
- Current AGENTS navigation: PASS; compact nested files, mojibake markers — 0.
- Dirty baseline preservation: PASS; сохранены все 23 tracked и 15 untracked исходных `nura_app/` paths, новых code/test/runtime paths Stage 2A не добавлено; migrations не менялись; `STATE.md` остался `M`.
- Required migration artifacts: PASS, 14/14 на месте; owner-decisions copy byte-identical исходнику.
- Limited secret scan: PASS, 73 документационных файла, совпадений — 0; значения секретов не выводились.
- Application tests: NOT RUN — этап documentation-only и не изменяет application behavior.

## Graphify

Graphify update is not required: Stage 2A меняет только documentation authority/navigation и не изменяет production architecture, Python packages, routes, services, repositories или dependency direction.
