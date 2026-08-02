# NURA — coordinated production release contract

> Одноразовый переход на закрытый owner-only prelaunch описан в
> [docs/current-vps-prelaunch.md](docs/current-vps-prelaunch.md). Это только
> `RUNBOOK — NOT EXECUTION PROOF`: он не заменяет coordinated immutable release
> contract ниже и отдельно требует approval на VPS inventory, backup,
> stop/migration/deploy/rollback/cleanup. Автоматический database rollback не
> заявляется.

> `docker-compose.sandbox.yml` не является production deploy path. Он описывает
> отдельный fail-closed внешний sandbox и не должен запускаться через production
> workflows или команды этого документа. Sandbox execution требует отдельного
> owner approval и предварительного offline preflight по
> [docs/external-sandbox-profile.md](docs/external-sandbox-profile.md).

> **STATUS: CURRENT OPERATIONS CONTRACT — EXTERNAL ACTIONS REQUIRE CURRENT AUTHORIZATION**
>
> Сохранено в стабильном root path на Stage 2A, чтобы не ломать release tooling/references. Не является production evidence и не разрешает deploy.

> **DO NOT DEPLOY.** Merge P4.2B2 сам по себе не разрешает host transition или production activation. До первого запуска обязательны P4.1B, migration/API compatibility review, отдельный dry-run перехода, финальный deploy-readiness audit и новое явное approval владельца.

## Owner-prelaunch migration-aware transition

Новый general production release по-прежнему fail closed при migration delta.
Единственное расширение — отдельный one-time engine
`scripts/current_vps_prelaunch_transition.py`, описанный в
[production secret and migration transition](docs/production-secret-and-migration-transition.md).
Он принимает только canonical tracked authorization manifest schema v2:
`origin/main` обязан быть отдельным manifest-only commit поверх exact target
base. Engine проверяет exact source/target/schema/artifact/engine identities,
реальные backup artifacts, running fleet identity и уже применённый target head.
Manifest с target `T` намеренно отсутствует в текущем implementation milestone;
без последующего authorization commit deploy остаётся заблокирован.

Base production Compose использует `RUN_MIGRATIONS=0`. Ни обычный workflow, ни
`deploy.sh` не применяют Alembic upgrade/downgrade. После отдельно разрешённого
engine apply `deploy.sh` допускает exact pre-applied delta только если helper
повторно проверил tracked manifest; общий `allow_migrations` не существует.

## Разрешённые entrypoints

Production release и rollback обычно запускаются только вручную из ветки `main` через защищённый GitHub Actions environment `production`:

- **Deploy coordinated production release** собирает immutable artifact точного `github.sha`, передаёт его в уникальный incoming path и вызывает `deploy.sh deploy <sha> <archive> <checksum> <manifest>`;
- **Roll back coordinated production release** требует точный SHA и явное acknowledgement, после чего вызывает `deploy.sh rollback <sha>`.

Оба workflow используют concurrency group `deploy-production` с `cancel-in-progress: false`. Push/merge не запускает deployment. CLI bypass, moving `git pull`, произвольный checkout, `workflow_dispatch` из implementation-задач и автоматический deploy запрещены. Единственное исключение — одноразовый audited P6B wrapper `scripts/deploy_audited_p6b_transition.sh`: он существует потому, что immutable target `9da6ad8…` предшествует migration-gate fix, разрешает только этот exact target/revision и извлекает engine и его pre-fast-forward helpers из закреплённого commit `f8716a7…` с проверкой exact Git blob, а не из mutable working tree. Engine управляет отдельным production checkout `/opt/nura`, который остаётся на `d0d39ae…` до fast-forward к exact target; helper-файлы живут только в private temporary directory и не загрязняют production checkout. После P6B этот wrapper не является общим deploy entrypoint.

Legacy audit name **Deploy to production** сохранён здесь только как ссылка на прежний P4.2B1 contract; оператор по-прежнему использует GitHub Actions → **Run workflow**, но новый workflow называется **Deploy coordinated production release** и всегда фиксирует exact target SHA. Он не публикует static in place. Локальный `scripts/deploy.sh` остаётся fail-closed deprecated stub; fallback и emergency deploy не поддерживаются.

## Immutable static artifact

`scripts/build_release_artifact.py` собирает deterministic `nura-static-<sha>.tar.gz`, checksum sidecar и публичный `release-manifest.json`. Источником служит tracked allowlist точного checkout; release unit включает landing/legal/mini/success, `vk-callback.html`, admin, PWA, assets, icons, fonts, VK SDK, metadata, Tarot originals и будущие tracked файлы разрешённых public directories.

Artifact имеет стабильный порядок, uid/gid, owner names, modes и mtime из commit timestamp. `VERSION` также выводится только из SHA и commit timestamp. Перед extraction проверяются outer checksum, каждый tar member, отсутствие traversal/links/special files, полный inventory, count, размеры, SHA-256 и aggregate manifest digest. Extraction разрешён только в уникальный staging directory.

Host layout после отдельно одобренного transition:

```text
/var/www/nura-releases/
  releases/<40-char-sha>/
  staging/<sha>-<unique-run-id>/
  current -> releases/<sha>

/var/lib/nura-release-state/
  releases/<sha>.json
  current.json
  previous.json
  logs/

/var/tmp/nura-release-incoming/<unique-run-id>/
/var/backups/nura-release-transition/
```

Staging и final releases обязаны находиться на одном filesystem. Staging→final выполняется directory rename. Существующий final release никогда не перезаписывается: полное совпадение manifest/hashes допускает reuse, любое расхождение блокирует операцию. `current` меняется через проверенный временный sibling symlink и atomic rename/replace.

## Coordinated activation

Под common `flock` root engine выполняет:

1. host layout, exact ref, clean checkout, current state и active Nginx gates;
2. migration delta gate с единственным exact исключением для отдельно отрепетированного и уже применённого перехода `d0d39ae… → 9da6ad8…`: оператор обязан передать exact revision acknowledgement и подтверждение обратной совместимости, а engine независимо сверяет target Alembic head и production `alembic_version`;
3. artifact checksum/inventory и dynamic disk/inode gates;
4. unique staging, verification и same-filesystem finalization;
5. уникальный candidate image `nura-release-candidate:<sha>-<run-id>` из exact tracked archive с OCI revision/source/created labels, проверка его image ID/labels и однократная публикация отсутствующего final tag `nura-release:<sha>`;
6. activation API, bot, celery-worker, celery-beat и admin-bot с `RUN_MIGRATIONS=0`;
7. проверку container uniqueness, running/health, exact tag, image ID и revision label;
8. atomic static `current` switch;
9. public smoke и только затем atomic release-state update;

Один SHA имеет одну immutable release identity: archive checksum, manifest checksum, static path, final image tag/ID, OCI labels и пять service image mappings/IDs записываются до первой application mutation и далее не меняются. Существующий final static или final tag без полного state-record считается recovery-ситуацией и не перезаписывается. Повторная активация ранее successful/rolled-back release (либо failed release только после доказанной полной compensation) переиспользует точные static/image provenance без rebuild и без повторной записи static. Отсутствующий final tag можно восстановить только из записанного локального image ID после полной сверки labels; конфликтующий tag блокирует операцию.
10. best-effort locked retention cleanup.

Postgres и Redis проверяются, но не пересоздаются. `deploy.sh` не запускает Alembic upgrade/downgrade и не имеет общего `allow_migrations`: любой delta в `nura_app/alembic/versions` блокирует release до extraction, Docker build и active mutations, кроме единственного зафиксированного перехода `d0d39ae… → 9da6ad8…`. Для него обязательны `NURA_PREAPPLIED_MIGRATION_REVISION=d1e2f3a4b5c6` и `NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA=1`; engine вычисляет head из target Git blobs и read-only проверяет production revision. Любая другая пара SHA или revision остаётся заблокированной.

Если application activation ломается до static switch, static остаётся прежним, а все изменённые application services возвращаются к предыдущей service→image mapping. После static switch compensation сначала возвращает static, затем application fleet, проверяет прежний `VERSION` и не помечает target successful.

## Rollback

Authoritative operational history хранится в `activation_history`: не более двух exact SHA, newest first, без duplicate и без текущего SHA. Для старого state без поля history считается пустой. При каждой успешной activation или rollback новая history строится из прежнего current и его history с удалением target/duplicate и ограничением до двух элементов. `previous_successful_sha` сохраняется только для backward compatibility и не используется как linked-list authority.

Автоматический rollback допустим только к SHA из `current.activation_history`, если target state successful/rolled_back и rollback-eligible, migration delta отсутствует, а static/image provenance полностью доступна. Это разрешает rollback/roll-forward к непосредственной предыдущей activation и ко второму защищённому target без циклического обхода per-SHA records. `previous.json` остаётся atomic snapshot непосредственного предыдущего current и обязан совпадать с `activation_history[0]`.

Порядок rollback фиксирован: atomic static switch назад, coordinated application activation из target record, runtime/public verification, затем state pointers. Database restore и Alembic не входят в rollback.

## Atomicity boundary

Гарантируются filesystem-atomic staging→final rename и atomic replacement directory entry `current`. Application activation пяти сервисов и compensation координируются и проверяются, но не являются атомарными. Docker containers заменяются во времени, PostgreSQL/Redis сохраняют независимое состояние, а browser/service-worker cache может пережить release. Нельзя заявлять full-system atomic deploy или database rollback.

## Nginx и one-time transition

Tracked config обслуживает release-owned static из `/var/www/nura-releases/current/public`, а ACME остаётся на `/var/www/nura-ai.ru`. Обычный release не меняет и не reload Nginx. Preflight требует ровно один enabled canonical config и fail-closed сообщает о незавершённом transition.

`scripts/prepare_atomic_release_host.py` по умолчанию выполняет read-only inventory и вычисляет exact non-ACME extras как `legacy − immutable release − .well-known/acme-challenge/`. JSON содержит ordered path/size/SHA-256/mode/uid/gid, count, bytes и aggregate digest. `--drop-candidate-output` пишет вне repository deterministic canonical candidate со status `owner_review_required`; helper никогда не утверждает его самостоятельно.

Если extras есть, отдельно owner-approved host-transition block должен передать `--approved-drop-manifest` со status `approved`, exact production SHA, legacy inventory digest и полностью совпадающим ordered extra inventory/digest. Missing, candidate-status, changed или newly appeared entry блокирует apply. Approved manifest копируется в forensic evidence. Все extras остаются в snapshot и `/var/www/nura-ai.ru`; после Nginx switch они перестают обслуживаться, кроме ACME subtree, который продолжает использовать legacy root.

Apply mode требует `--apply`, exact legacy SHA `d0d39ae8717ceb0920d98f27dd9092f746755c6c`, exact reviewed `--target-sha`, `--acknowledge-production-change` и canonical roots. До первой active mutation legacy `/var/www/nura-ai.ru/VERSION` обязан иметь строго старый формат `<sha> - YYYY-MM-DDTHH:MM:SSZ\n`: lower-case audited SHA, exact separator и ровно один final newline; timestamp deployment не сверяется с commit timestamp. В этой pre-transition и restore фазах все остальные manifest bytes сверяются с deterministic legacy artifact, а `VERSION` — с сохранёнными фактическими bytes/hash; `legacy-public-baseline.json` фиксирует schema, SHA, VERSION size/hash/parsed SHA/timestamp, manifest hash, alias/health/redirect checks и время записи. После switch и при `already_prepared` применяется полная deterministic public verification, включая artifact `VERSION`. Deterministic legacy artifact сначала проверяется в unique staging; exact существующий final release переиспользуется только после полной сверки manifest/hashes/digests, mismatch создаёт recovery evidence. Все public/extras/approval/image/state prechecks выполняются до active Nginx/current mutation. Ошибка до mutation оставляет production неизменённым и безопасно очищает только staging; verified final/tag остаются для retry. Ошибка после mutation восстанавливает прежние configs/current/public baseline, после чего retry переиспользует exact material. Полностью подготовленный host проходит exact verification и возвращает `already_prepared` без reload или перезаписи; partial current/state disagreement требует recovery. `/var/www/nura-ai.ru` и legacy evidence не удаляются.

Release-artifact job использует те же фиксированные runtime versions, что обычный CI: Python 3.11.9 и Node.js 24.15.0, с явным выводом версий. GitHub artifact digest не участвует в identity: authoritative checks остаются внутри archive checksum sidecar и public manifest.

Эта implementation-задача helper не запускает, host files не меняет, workflow не dispatch-ит и production activation не выполняет.

## Retention

Под common lock защищаются current и ровно два SHA из authoritative `current.activation_history`; legacy evidence всегда защищено отдельно. Retention не обходит `previous_successful_sha`, поэтому rollback/roll-forward не создаёт циклы и непосредственная предыдущая activation после rollback не удаляется. CI artifact хранится 14 дней. Internal logs/state — 30 дней, кроме protected successful и legacy evidence. Failed/incomplete staging старше 7 дней ограничивается двумя сохранёнными экземплярами. Успешный deploy удаляет только свой validated direct-child incoming directory; неуспешные incoming directories старше 7 дней также ограничиваются двумя экземплярами. Cleanup не следует symlinks, не трогает unrelated Docker images и не откатывает успешный release; failure логируется, а следующий release всё равно обязан пройти disk/inode gate.
