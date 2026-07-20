# NURA — production deployment contract

## Единственный штатный trigger

Production deployment запускается только вручную:

1. GitHub Actions.
2. Workflow **Deploy to production**.
3. **Run workflow** для ветки `main`.
4. Approval защищённого environment `production`.

Обычный push или merge в `main` не запускает production deployment. Локальный CLI, SSH fallback и emergency deploy не поддерживаются.

## Exact-SHA flow

Workflow один раз фиксирует target как SHA выбранного запуска (`github.sha`), проверяет его принадлежность `origin/main`, извлекает `deploy.sh` непосредственно из этого commit во временный launcher и передаёт ровно этот 40-символьный SHA в entrypoint. Поэтому первый запуск после merge уже использует новый exact-target contract, даже если production checkout ещё содержит старую версию скрипта. Серверный entrypoint:

- получает общий host lock;
- требует чистый checkout ветки `main` без незавершённых Git-операций;
- проверяет принадлежность target истории `origin/main`;
- разрешает только fast-forward к exact target;
- проверяет `HEAD == target`;
- выполняет metadata, manifest, migration и source gates до production-файлов;
- публикует tracked manifest entries и проверяет SHA-256 источников и назначений;
- собирает общий API/admin-bot image только из `git archive` exact target, не включая ignored host state или `.env` в build context;
- принудительно отключает Alembic в deployment Compose override, ожидает запуска API/admin-bot и выполняет smoke checks;
- валидирует nginx с восстановлением предыдущего конфига при ошибке validation/reload;
- записывает `VERSION` последней операцией, начиная строку с exact target SHA.

Moving `git pull` не является частью deployment contract. Запрещены прямое редактирование production checkout, stash/pop prod-only правок, `git add -A`, локальный push как стадия deploy и ручной Docker rebuild в качестве deploy.

## Migration delta gate

Input `allow_migrations` по умолчанию равен `false`. Entry point сравнивает `nura_app/alembic/versions` между SHA из текущего production `VERSION` и target SHA.

Если найдена разница, deployment останавливается до любых static/nginx/API mutations, пока после отдельной readiness-проверки не передано явное boolean-значение `true`. Approval только разрешает target с проверенной migration delta: deploy script не вызывает Alembic migration или downgrade самостоятельно и не является подтверждением совместимости схемы.

Значения `false`, `0`, `no` и пустая строка не разрешают migration delta.

## Проверка релиза

Корневой entrypoint проверяет обязательные endpoints до записи `VERSION`, а workflow после завершения повторно проверяет публичный контракт:

- `/VERSION`;
- `/service-worker.js`;
- `/pwa-release.js`;
- `/pwa-release.json`;
- `/manifest.json`;
- `/offline.html`;
- `/app/`;
- `/app/index.html`;
- `/app/nura-pwa.js`;
- `/health`.

Проверка требует exact SHA в `VERSION`, валидный release JSON, одинаковый release ID в JS/JSON, ожидаемый import в service worker, соответствие публичных metadata tracked source и canonical redirect с `www` на apex.

## Deprecated CLI

`scripts/deploy.sh` сохранён только как fail-closed deprecated stub. Он всегда завершается ненулевым кодом, ничего не публикует и указывает на approved manual GitHub Actions workflow. Его нельзя использовать как fallback.

## Текущие ограничения

P4.2B1 всё ещё копирует файлы in place и не удаляет stale destinations, исчезнувшие из следующего manifest. Atomic release-directory activation, чистый inventory и rollback относятся только к P4.2B2.

**DO NOT DEPLOY после merge P4.2B1.** Production deployment остаётся запрещён до завершения P4.2B2, P4.1B, API/migration readiness review, финального deploy-readiness audit и отдельного явного approval владельца.

Если workflow отклоняет server checkout, migration delta или release contract, состояние production нельзя исправлять вручную. Требуется отдельный read-only разбор причины и согласованное изменение через repository workflow.
