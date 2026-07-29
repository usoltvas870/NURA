# NURA — Session Journal

Status:

`NON-NORMATIVE SESSION JOURNAL`

## 1. Purpose and authority boundary

Этот файл хранит только краткую датированную chronology существенных этапов NURA.
Он не является product specification, current implementation mirror, current
roadmap, operations runbook, acceptance evidence или owner-decision register.

Действующие источники перечислены в разделе [Current authority destinations](#5-current-authority-destinations).
Текущий статус всегда проверяется по этим источникам, а не по старым записям
журнала. Отсутствие факта в `STATE.md` ничего не отменяет; наличие старого факта
в `STATE.md` не делает его current. Подробные предыдущие версии журнала доступны
через Git history.

## 2. Maintenance rules

- Добавляются только датированные historical entries или записи с однозначным
  commit/baseline.
- Journal не содержит current roadmap, transient next-session instructions,
  неподтверждённых production statements или текущих owner decisions.
- Credentials, access targets, machine-specific key paths, direct deployment
  commands и private operational details здесь не фиксируются.
- Подробные implementation, acceptance и operations facts должны находиться в
  соответствующих domain documents.
- Старые подробные записи сохраняются через Git history, а не копируются в
  активный body.

## 3. Historical milestone index

| Date / commit | Historical milestone | Current authority destination |
|---|---|---|
| 2026-07-27 — `61977175ef3b88fad618674fca2554db60aae379` | Последний ранее committed detailed journal baseline; этап full-matrix Telegram delivery. Это historical implementation milestone, не полный current status. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 2026-07-28 — `b70d6ccf8bbeac49b77015be09295a41060fc9bd` | Committed code/acceptance baseline. Его исторический evidence: targeted `147 passed`, PostgreSQL race `3 passed`, safe suite `1081 passed`, `22 skipped`, `1 deselected`, `0 failed`. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 2026-07-28 — `7cc1122773656cb73847de70adee628a7f843e4e` | Установлены documentation authority, routers и границы legacy/current/future. | [Documentation router](docs/README.md), [architecture router](docs/architecture/README.md) |
| 2026-07-29 — `9a5a9be5ef12faba9a425b57ee0432da8a452464` | Stage 2B documentation consolidation завершена отдельным принятым commit; domain documents получили согласованные authority classifications. | [Documentation router](docs/README.md) |

Указанные результаты принадлежат своим датам и baseline. Они не заменяют
проверку текущего code/tests/config или нового acceptance evidence.

## 4. Sessions 92–100 — historical summary

| Session | Date / baseline | Historical milestone | Current evidence destination |
|---|---|---|---|
| 92 | 2026-07-27; worktree rooted at `61977175ef3b88fad618674fca2554db60aae379` | Упакован local Telegram-first acceptance runner с disposable PostgreSQL/Redis, migration round-trip и fake external boundaries; это не было external или production proof. | [Acceptance router](docs/acceptance/README.md) |
| 93 | 2026-07-27; worktree after `6197717` | Cumulative local PostgreSQL path прошёл onboarding, mini-report delivery/replay и Daily Tarot durability; исправлено обнаруженное schema/model расхождение без новой migration. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 94 | 2026-07-27; worktree after `6197717` | Local golden path продолжен через full-report generation; исправлена поддержка order-linked report lifecycle, добавлен focused regression evidence. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 95 | 2026-07-27; worktree after `6197717` | Подтверждены manual resend и fresh-process replay без повторной генерации или повторного transport side effect. | [Acceptance router](docs/acceptance/README.md) |
| 96 | 2026-07-27; worktree after `6197717` | Подтверждён fresh-process durability replay накопленного local flow; documented non-exactly-once boundaries сохранялись. | [Acceptance router](docs/acceptance/README.md) |
| 97 | 2026-07-27; worktree after `6197717` | Local refund/account-deletion replay выявил и закрыл visibility и Redis cleanup defects; financial retention оставалась отдельным contract. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 98 | 2026-07-27; worktree after `6197717` | Принят local failure/retry proof с fresh-process replay и fail-closed cleanup disposable infrastructure. | [Acceptance router](docs/acceptance/README.md) |
| 99 | 2026-07-28; pre-`b70d6cc` worktree | Принят local security/redaction stage; исправлены error logging и refund verification/fencing defects, затем выполнены scoped local checks. | [Current implementation](docs/implementation/current-status.md), [acceptance](docs/acceptance/README.md) |
| 100 | 2026-07-28; dated worktree evidence, не единый commit SHA | Зафиксирован итог local readiness review. Результат `1059 passed`, `22 skipped`, `1 deselected`, `0 failed` остаётся immutable dated evidence только своего manifest-specific baseline и не приписывается `b70d6cc`. External sandbox и production этим не доказаны. | [Dated acceptance routing](docs/acceptance/README.md) |

Historical source содержит пустой дублирующий заголовок `Session 93` перед
`Session 94`; это numbering anomaly исходного журнала, а не отсутствующий этап,
которому можно приписать вымышленное содержание.

Дополнительные датированные записи того же source period сохраняют два
milestone без номера session: local automatic-delivery acceptance и local
required-service boot/runtime-topology smoke от 2026-07-27. Их подробный и
текущий evidence проверяется по [acceptance router](docs/acceptance/README.md) и
[current implementation mirror](docs/implementation/current-status.md); записи
не доказывают внешний sandbox или production.

## 5. Current authority destinations

- Product target: [canonical NURA 1.0 / 1.5 specification](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current implementation: code, migrations, tests, configuration и [current implementation mirror](docs/implementation/current-status.md).
- Documentation authority: [documentation router](docs/README.md).
- Technical navigation: [architecture router](docs/architecture/README.md).
- Acceptance: [acceptance evidence router](docs/acceptance/README.md).
- Operations: [Admin Bot operations contract](ADMIN_BOT_SPEC.md) и [deployment contract](DEPLOY.md).

## 6. Historical preservation note

Подробный committed pre-consolidation body сохранён в Git history, включая
baseline `61977175ef3b88fad618674fca2554db60aae379` и более ранние версии.
Незакоммиченные additions Sessions 92–100 не существовали там как отдельный
Git blob; их materially useful chronology сохранена в summary выше. Активный
journal намеренно не воспроизводит obsolete, transient или sensitive operational
details. Их удаление из active body не переписывает repository history.
Sanitization active body не доказывает компрометацию credentials: external
exposure старых Git blobs в этой работе не оценивалась, а переписывание Git
history и ротация credentials/secrets не выполнялись; любые дальнейшие
security-действия требуют отдельной оценки external exposure.
