# Current VPS owner-only prelaunch

> **STATUS: RUNBOOK — NOT EXECUTION PROOF**
>
> Этот документ описывает одноразовый переход на закрытый prelaunch. Он не
> разрешает подключение к VPS, backup, остановку сервисов, миграции, очистку,
> deploy или внешние provider calls. Каждая изменяющая host операция требует
> отдельного актуального approval владельца.

Production secret-file profile, offline preflight, exact migration chain и
двухкоммитный authorization contract описаны в
[production secret and migration transition](production-secret-and-migration-transition.md).
Этот implementation milestone не создаёт target-bound manifest и потому не
разрешает execution.

## 1. Зафиксированное решение и границы

На текущем этапе отдельные sandbox VPS, hostname, bot и stack не создаются.
После отдельного deploy approval используются текущие production VPS, hostname,
Telegram-бот, PostgreSQL/Redis и production DeepSeek credentials/endpoint/model.
YooKassa отложена: prelaunch запускается только с
`PRELAUNCH_OWNER_ONLY=true`, явным непустым
`PRELAUNCH_TELEGRAM_ALLOWED_USER_IDS` ровно с одним owner ID, совпадающим с
`ADMIN_TELEGRAM_ID`, и `PAYMENTS_ENABLED=false`.

Сейчас клиенты, платежи и ценные пользовательские данные не ожидаются, но это
не является разрешением на удаление. Текущее application state можно считать
disposable только после проверенного backup и отдельного owner approval на
конкретную очистку.

## 2. Обязательные stop criteria

Переход останавливается до первой mutation, если:

- неизвестны deployed commit, активные service definitions или bot identity;
- backup PostgreSQL, минимального Redis/state или конфигурации не создан либо не
  проверен на читаемость;
- allowlist пуст, содержит не ровно один ID либо не совпадает одновременно с
  Telegram ID владельца и `ADMIN_TELEGRAM_ID`;
- `TEST_MODE` или internal payment shortcut включены;
- `PAYMENTS_ENABLED` не равен `false`, присутствует публичный payment path либо
  prelaunch readiness не проходит;
- выбранная database revision не совпадает с Alembic head exact release;
- release не привязан к reviewed exact SHA;
- любой секрет попал в terminal log/evidence;
- требуется очистка, migration или deploy без отдельного текущего approval.

## 3. One-time transition checklist

Ниже приведён порядок и ожидаемое evidence, а не готовые shell-команды.
Намеренно нет команд с незаполненными параметрами.

1. **Read-only host inventory.** Зафиксировать OS, disk/inodes, Docker/runtime,
   active containers/services, volumes, networks, открытые listeners, Nginx
   enabled config, certificates, PostgreSQL/Redis endpoints и release-state
   paths. Значения secrets не читать и не печатать.
2. **Текущий deployed SHA.** Сопоставить release state, image OCI revision,
   application `VERSION` и exact Git commit. Любое расхождение считать
   recovery-ситуацией.
3. **Bot identity без token.** Через локально настроенную runtime identity
   получить только numeric bot ID и username; сравнить с утверждённой
   production identity. Token и его fingerprint не включать в evidence.
4. **PostgreSQL backup.** Создать timestamped logical backup выбранного
   production database, сохранить checksum, размер, владельца evidence и
   retention location. Выполнить неразрушающую проверку читаемости архива.
5. **Минимальный Redis/state backup.** Сначала определить, какие durable queues,
   delivery/retry/idempotency keys и release-state действительно нужны.
   Сохранить согласованный snapshot и metadata. Не считать Redis заменой
   PostgreSQL backup.
6. **Configs и service definitions.** Снять private snapshot Compose/systemd,
   Nginx, environment-file names, secret-file mappings и release records.
   Значения secrets в human-readable evidence не копировать.
7. **Controlled stop.** После отдельного approval остановить старые bot, API,
   worker и Beat в согласованном порядке, убедиться, что polling, scheduled
   sends и background writes прекращены. Database/Redis пока не удалять.
8. **Owner database decision.** Владелец письменно выбирает одно:
   сохранить текущую database либо создать новую пустую database на том же VPS.
   Очистка существующей database/Redis не следует автоматически ни из одного
   выбора и требует отдельного approval после backup.
9. **Migration выбранной database.** До apply сравнить current revision с
   exact hashed chain `d1e2f3a4b5c6 → d8e9f0a1b2c3`, отдельно проверить
   tracked authorization manifest и зафиксировать forward-only plan. Применить
   migration только после отдельного approval. Этот runbook не обещает
   Alembic/database rollback.
10. **Deploy exact reviewed SHA.** Использовать coordinated immutable release
    contract из root `DEPLOY.md`; не применять moving branch, `git pull` или
    mutable image tag. Записать SHA, artifact/manifest checksums и image
    revisions.
11. **Owner-only configuration.** Запустить application fleet с production
    security gates, current DeepSeek settings, payments off и ровно один owner
    ID, совпадающий с `ADMIN_TELEGRAM_ID`. YooKassa shop/key/file settings
    намеренно отсутствуют и запрещены readiness; sandbox mode не
    используется.
    Plaintext credentials в `.env` запрещены: используются только exact
    per-service mounts из `/opt/nura/secrets/production/`.
12. **Allowlist before polling.** До первого bot polling выполнить offline
    readiness, затем с polling off проверить `/ready` (DB/Redis/AI и
    `payment_configuration=disabled`), worker ping, running Beat, exact OCI
    revisions и runtime owner allowlist/YooKassa absence. При отрицательном
    результате bot остаётся остановленным. Polling включается последним.
13. **Smoke tests.** Только с allowlisted owner проверить `/start`, onboarding,
    profile, mini text/PDF, My Materials/resend, Daily Card, пять chat responses
    и quota/retry, governed prompts, admin-authenticated prelaunch full report
    generation plus text/PDF/resend, broadcast test-send себе, opt-out и account
    deletion. Подтвердить отсутствие Order/PaymentAttempt/provider calls и
    массовых sends. BotFather profile меняется, если потребуется, только
    отдельной ручной операцией владельца после deploy.
14. **Application rollback.** При failed smoke вернуть exact предыдущие static
    и service image mappings по coordinated rollback contract. PostgreSQL,
    Redis и Alembic автоматически не откатываются; при несовместимом schema/data
    change остановиться и использовать отдельно одобренный recovery plan из
    backup.
15. **Cleanup после PASS.** Старые containers/images/state и тем более
    database/Redis удаляются только после зафиксированного PASS, проверки
    backup/retention и отдельного approval на точные targets.

## 4. Approval points

Отдельное актуальное approval необходимо как минимум перед:

- любым подключением к VPS и даже read-only inventory;
- backup, если он требует доступа к production credentials;
- остановкой сервисов;
- выбором новой/существующей database и любой очисткой;
- применением migration;
- deploy или rollback;
- первым Telegram/DeepSeek smoke call;
- cleanup.

Локальные tests и этот документ не являются доказательством выполнения ни
одного пункта.
