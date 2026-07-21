# Disposable PostgreSQL backup/restore proof

## Purpose and boundary

The P5B runner proves that the repository schema and deterministic synthetic
fixtures can be backed up and restored with PostgreSQL 16.13. It is a
release-readiness test, not a production backup executor.

The runner does not accept a DSN. It creates two physically separate,
uniquely named PostgreSQL containers, an isolated Docker network, unique
database names, and ephemeral credentials. All resources carry these labels:

```text
nura.purpose=p5b-backup-restore-proof
nura.run_id=<unique-run-id>
```

Only synthetic data is allowed. Production data, production identifiers,
real email domains, real phone values, access tokens, private keys, session
cookies, and other PII are prohibited. The runner does not read `.env` or
application runtime settings and does not start API, bot, worker, beat, or
admin services.

## Backup contract

The source schema is created only by a normal `alembic upgrade head` against a
new PostgreSQL 16.13 database. The full application database is dumped without
schema or table filters. The canonical command is semantically equivalent to:

```text
pg_dump --format=custom --no-owner --no-acl \
  --file=<external-synthetic-artifact> <synthetic-source-database>
```

The custom archive is stored outside the repository. The runner requires mode
`0600` on POSIX or a non-inherited, current-user-only ACL on Windows and
re-verifies protection before checksum and restore. A SHA-256 checksum,
deterministic JSON manifest, and `pg_restore --list` catalog are required before
restore.

Backup validity depends on quiescence. Immediately before and after the dump,
the runner requires no other client connections, records transaction snapshot
metadata and database DML counters, and re-snapshots source schema, rows, data
checksums, and sequences after the dump. The database session counter is
reconciled with the exact number of proof-opened connections plus the one
canonical `pg_dump` session. Any unexpected client, completed read-only session,
completed DML, or source drift invalidates the archive and blocks restore. This
simulation proves the gate contract; it does not prove production quiescence
capability.

## Restore and hard gates

Restore uses a different, newly created PostgreSQL 16.13 container and database.
The target gate rejects any user schema object, application table, or
`alembic_version` row. Existing objects are never removed to bypass this gate.

The canonical restore is semantically equivalent to:

```text
pg_restore --exit-on-error --no-owner --no-acl \
  --dbname=<empty-synthetic-target> <synthetic-artifact>
```

`--clean`, `--create`, parallel restore, cluster-global restore, and Alembic
downgrade are not used. A PASS requires all of the following:

- archive presence, non-zero size, SHA-256 match, and readable catalog;
- PostgreSQL server and client major version 16;
- distinct disposable source and target identities and an empty target;
- zero restore exit code;
- source, target, and repository Alembic revision equality;
- source and target schema fingerprint equality;
- catalog table, column, constraint, index, sequence, view, function, trigger,
  type, and extension equality;
- per-table row-count and deterministic data-checksum equality;
- sequence-state equality;
- validated constraints and valid/ready indexes;
- no unexpected public application objects;
- synthetic PII and production-marker guards;
- measured backup, restore, verification, total, startup, and throughput data;
- successful cleanup of the exact labeled containers and network.

The schema fingerprint follows the repository reconciliation convention: rows
remain in canonical column order, while raw `ordinal_position` numbers are
excluded because a historical dropped-column tombstone is intentionally
compacted by logical dump/restore. Names, types, nullability, defaults,
identity/generated attributes, constraints, and indexes remain fingerprinted.

Table data checksums use catalog column order, canonical row sorting, stable
JSON representation, and explicit encodings for NULL, timestamps, dates,
decimals, UUIDs, bytes, booleans, integers, JSON objects, and arrays. Physical
row order is never used.

## Fail-closed coverage

Unit contracts reject production-like identifiers, source/target collisions,
remote hosts, missing or empty archives, checksum drift, invalid manifests,
wrong client major versions, non-empty targets, revision/fingerprint drift, and
fixture-checksum drift.

The PostgreSQL integration proof additionally demonstrates rejection or
detection of a corrupted archive, a non-empty target, an unexpected synthetic
application transaction, row-count drift, deterministic data-checksum drift,
sequence drift, and source/target identity collision. The synthetic session
used by the quiescence negative test closes itself; the runner never terminates
database sessions.

## Local invocation

Run Python commands from `nura_app/`. The evidence directory must be new or
empty and outside the repository:

```powershell
python tools/backup_restore_proof.py `
  --synthetic-disposable-proof `
  --evidence-dir C:\git\NURA-safety\2026-07-21-p5b-backup-restore-proof
```

If the exact official image is not already present, the explicitly authorized
option below permits only `postgres:16.13` to be pulled:

```powershell
python tools/backup_restore_proof.py `
  --synthetic-disposable-proof `
  --pull-image-if-missing `
  --evidence-dir <new-external-directory>
```

Omitting `--synthetic-disposable-proof` fails before any resource is created.
Cleanup executes in `finally`. Intended resource names are registered before
creation, every resource is verified against both run labels before removal,
and cleanup continues across independent Docker errors. Failure evidence is
retained, while only the current run's labeled containers, anonymous volumes,
and network are removed. No prune command is used. The manifest and final
report remain pending until cleanup passes; cleanup failure finalizes them as
FAILED, never PASS.

## Evidence layout

The external evidence directory contains numbered preflight, environment,
source, migration, fixture, quiescence, backup, restore, catalog, data,
sequence, object, PII, timing, fail-closed, test, cleanup, Git, PR, CI, and final
report files. `artifacts/` may contain only the synthetic custom archive and
machine-readable manifests. `SHA256SUMS.txt` covers the evidence tree and must
be regenerated and verified after final PR/CI evidence is recorded.

The archive must not be uploaded as a public CI artifact. Ordinary CI runs the
integration contract with an ephemeral pytest evidence directory; pytest and
the runner remove the archive and all Docker resources afterward. The existing
test job already discovers the new tests, so no manual workflow or
`workflow_dispatch` is required.

## Encryption and production limitations

P5B does not choose production encryption. The runner performs bounded version
discovery for `age`, `rage`, and `gpg`. If an available tool has the required
key-generation/decryption capability, it performs an ephemeral-key or
ephemeral-passphrase encryption/decryption round-trip and verifies the decrypted
SHA-256 without retaining private key material. GPG runs with a protected
temporary `GNUPGHOME` and forced OpenPGP integrity protection; the temporary
home is removed with the private passphrase state. When no suitable tool is
available, the evidence states:

```text
NOT EXECUTED — PRODUCTION TOOLING DECISION PENDING
```

No crypto dependency is installed and no custom cryptography is implemented.
Production execution location, encryption tool, key custody, storage,
off-host transport, retention, deletion approval, capability audit, backup
approval, restore approval, and production RTO remain owner decisions.

The rehearsal ceilings are restore <= 15 minutes, verification <= 10 minutes,
and total <= 30 minutes. Synthetic P5B timing does not establish production
RTO, and production duration must not be extrapolated without a production-size
and capability audit.

Successful P5B does not authorize production backup, restore, migration, deploy,
session termination, or Alembic downgrade rollback.
