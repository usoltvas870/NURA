# NURA — coordinated production release contract

> **DO NOT DEPLOY.** Merge P4.2B2 сам по себе не разрешает host transition или production activation. До первого запуска обязательны P4.1B, migration/API compatibility review, отдельный dry-run перехода, финальный deploy-readiness audit и новое явное approval владельца.

## Разрешённые entrypoints

Production release и rollback запускаются только вручную из ветки `main` через защищённый GitHub Actions environment `production`:

- **Deploy coordinated production release** собирает immutable artifact точного `github.sha`, передаёт его в уникальный incoming path и вызывает `deploy.sh deploy <sha> <archive> <checksum> <manifest>`;
- **Roll back coordinated production release** требует точный SHA и явное acknowledgement, после чего вызывает `deploy.sh rollback <sha>`.

Оба workflow используют concurrency group `deploy-production` с `cancel-in-progress: false`. Push/merge не запускает deployment. CLI bypass, moving `git pull`, произвольный checkout, `workflow_dispatch` из этой implementation-задачи и автоматический deploy запрещены.

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
2. безусловный migration delta gate;
3. artifact checksum/inventory и dynamic disk/inode gates;
4. unique staging, verification и same-filesystem finalization;
5. один local image `nura-release:<sha>` из exact tracked archive с OCI revision/source/created labels;
6. activation API, bot, celery-worker, celery-beat и admin-bot с `RUN_MIGRATIONS=0`;
7. проверку container uniqueness, running/health, exact tag, image ID и revision label;
8. atomic static `current` switch;
9. public smoke и только затем atomic release-state update;
10. best-effort locked retention cleanup.

Postgres и Redis проверяются, но не пересоздаются. `deploy.sh` не запускает Alembic upgrade/downgrade и не имеет `allow_migrations`: любой delta в `nura_app/alembic/versions` блокирует release до extraction, Docker build и active mutations.

Если application activation ломается до static switch, static остаётся прежним, а все изменённые application services возвращаются к предыдущей service→image mapping. После static switch compensation сначала возвращает static, затем application fleet, проверяет прежний `VERSION` и не помечает target successful.

## Rollback

Автоматический rollback допустим только к current previous или одному из двух защищённых successful predecessors. Нужны verified static directory, internal state record и все service images. Arbitrary SHA, migration/schema incompatibility или отсутствующий image блокируют rollback.

Порядок rollback фиксирован: atomic static switch назад, coordinated application activation из target record, runtime/public verification, затем state pointers. Database restore и Alembic не входят в rollback.

## Atomicity boundary

Гарантируются filesystem-atomic staging→final rename и atomic replacement directory entry `current`. Application activation пяти сервисов и compensation координируются и проверяются, но не являются атомарными. Docker containers заменяются во времени, PostgreSQL/Redis сохраняют независимое состояние, а browser/service-worker cache может пережить release. Нельзя заявлять full-system atomic deploy или database rollback.

## Nginx и one-time transition

Tracked config обслуживает release-owned static из `/var/www/nura-releases/current/public`, а ACME остаётся на `/var/www/nura-ai.ru`. Обычный release не меняет и не reload Nginx. Preflight требует ровно один enabled canonical config и fail-closed сообщает о незавершённом transition.

`scripts/prepare_atomic_release_host.py` по умолчанию выполняет только read-only inventory. Apply mode предназначен для отдельного owner-approved блока и требует `--apply`, exact legacy SHA `d0d39ae8717ceb0920d98f27dd9092f746755c6c`, exact reviewed `--target-sha`, `--acknowledge-production-change` и canonical roots. Он сохраняет полный forensic snapshot/inventory, три строго разрешённых legacy Nginx файла, прежний sites-available config, пять service image mappings и protected tags, атомарно устанавливает tracked Nginx config exact target, создаёт legacy release/state, нормализует enabled config, делает `nginx -t` и reload только в apply mode. При ошибке Nginx или state commit прежние canonical/include configs и active symlink восстанавливаются. `/var/www/nura-ai.ru` и legacy evidence не удаляются.

Эта implementation-задача helper не запускает, host files не меняет, workflow не dispatch-ит и production activation не выполняет.

## Retention

Под common lock защищаются current и два предыдущих successful static/image sets. CI artifact хранится 14 дней. Internal logs/state — 30 дней, кроме protected successful и legacy evidence. Failed/incomplete staging старше 7 дней ограничивается двумя сохранёнными экземплярами. Успешный deploy удаляет только свой validated direct-child incoming directory; неуспешные incoming directories старше 7 дней также ограничиваются двумя экземплярами. Cleanup не следует symlinks, не трогает unrelated Docker images и не откатывает успешный release; failure логируется, а следующий release всё равно обязан пройти disk/inode gate.
