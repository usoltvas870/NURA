# P7B State B handoff and activation

This document describes the repository implementation of the controlled P7B
release path. It is an execution contract, not permission to run a deployment.
The production workflow remains manually dispatched, production-environment
protected, and serialized.

## Ownership boundaries

The release chain has three non-overlapping owners:

1. **Common prepare** validates the exact main-branch SHA and deterministic
   artifact, materializes the immutable static release and application image,
   writes a secret-free persistent handoff, and stops. In `prepare-p7b` mode it
   does not recreate Redis or application services and does not change
   `current.json`, the public `current` link, or the active `VERSION`.
2. **Managed P7B activation** bootstraps the previous runtime, owns every
   application mutation and the single compensation path, verifies Stage 1,
   changes only `APP_ENV` and `TEST_MODE`, verifies Stage 2, and produces a
   completion receipt.
3. **Canonical finalization** accepts only an integrity-valid Stage 2 receipt,
   re-verifies the live target runtime, preserves the previous canonical state,
   advances the public link and canonical state, and records `complete`.

The common engine remains the owner of mutation and compensation for the normal
non-P7B `deploy` path. It does not compensate a failed managed P7B activation.

## Persistent records

`/var/lib/nura-release-state/p7b` contains mode `0600` JSON envelopes and
materialized Compose inputs:

- `handoffs/<target>.json` — exact target SHA, release path, artifact digests,
  application image tag and IDs, non-empty Compose inputs and their SHA-256
  digests, expected baseline, and data volume names;
- `baselines/<target>.json` — canonical previous SHA, public target, exact live
  application image IDs, materialized rollback Compose inputs, and data volume
  identities;
- `transactions/<target>.json` — the current state-machine phase and explicit
  `compensation_owner: p7b`;
- `receipts/<target>.json` — Stage 2 proof bound to the digests of the handoff
  and baseline;
- `compose/` — persistent target and previous-runtime Compose material;
- `environment/` — the protected byte-for-byte pre-Stage-2 environment backup.

Each JSON envelope has an exact schema, kind, canonical payload digest, and no
unknown top-level fields. Reads fail closed for malformed JSON, schema drift,
digest mismatch, symlinks, unsafe paths, mutable image references, or runtime
identity mismatch. Environment contents are never copied into JSON or command
arguments.

The adjacent temporary Compose base is removed before the post-fast-forward
clean-check. After the exact checkout is proven clean, the base is rebuilt from
`<target>:nura_app/docker-compose.yml` through a mode `0600` temporary file and
an atomic replace, then parsed by Docker Compose. Common prepare will not persist
a handoff until both Compose inputs are regular, non-symlink, non-empty,
parseable, volume-valid, and bound to non-empty SHA-256 digests.

## State machine

The durable phases are:

```text
prepared
  -> baseline_ready
  -> stage1_intent
  -> stage1_verified
  -> stage2_intent
  -> stage2_verified
  -> smoke_verified
  -> finalizing
  -> complete
```

Failure before a verified stage moves through exactly one P7B-owned compensation
to `stage1_compensated` or `stage2_compensated`. Intent is persisted before the
corresponding mutation. A retry verifies completed work instead of repeating it.
`recover` chooses verification, compensation, or finalization from the durable
phase; it never infers success from a partially executed command.

## Baseline bootstrap

`bootstrap` requires the canonical state and public link to agree, requires
`APP_ENV=development` and `TEST_MODE=true`, verifies a single healthy application
fleet, captures exact application image IDs, verifies PostgreSQL and Redis
volumes, and materializes a rollback Compose context from the exact previous
commit. Mixed application revisions, unhealthy services, missing images, changed
volumes, or canonical/public disagreement fail closed.

PostgreSQL is never recreated. No volume deletion command is part of this path.

## Stage 1 and Stage 2

Stage 1 uses the handoff context to recreate Redis and the five application
services with immutable target images. It verifies Compose state, Redis,
PostgreSQL, API health, Celery, target identity, and unchanged data volumes.
Canonical and public markers remain on the previous release.

Stage 2 first writes a byte-for-byte environment backup, changes only:

```text
APP_ENV=production
TEST_MODE=false
```

It recreates only `api`, `bot`, `celery-worker`, `celery-beat`, and `admin-bot`.
It then verifies production readiness and writes the completion receipt. Failure
restores the environment and materialized previous runtime.

The single `activate` controller holds the same host-wide common release lock
used by the normal deploy/rollback engine for the complete managed chain. Its
canonical path is `/run/lock/nura-deploy.lock`; `/run/lock` is the root-owned
sticky system lock directory, and the lock file itself must be a regular,
root-owned, non-group/world-writable file. P7B's private state lock remains
`/var/lib/nura-release-state/p7b/rollout.lock` under a root-owned mode `0700`
directory; symlinks are rejected for both lock paths.
Before finalization, it sends only malformed payment webhook bodies
(`{`, array, string, and `null`) and requires HTTP 400. It does not send a valid
payment event or mutate entitlement state. A smoke failure or interruption
before durable `smoke_verified` restores the environment and previous runtime.

## Finalization and recovery

Finalization checks the receipt against both persistent input digests and
re-verifies the live Stage 2 runtime. It saves the previous canonical state,
atomically replaces the public symlink, validates target `VERSION`, atomically
writes the common-compatible per-release record and `current.json`, and records
`complete`. Only after durable completion, best-effort retention removes
unprotected old release directories and their exact `nura-release:<sha>` images;
the current SHA and activation history remain protected. Re-entry from
`finalizing` checks
the saved previous marker and safely finishes any remaining marker update.

The supported interruption points include after prepare, during and after
bootstrap, before and after both stage verifications, and during canonical
finalization. The persistent advisory lock is automatically released on process
death while the lock inode is retained for future runs. A full workflow rerun
detects an integrity-valid `smoke_verified`, `finalizing`, or `complete`
transaction for the exact target before invoking common prepare, so it can
resume a partially switched public/canonical marker pair. That early-resume path
also validates and removes the exact newly transferred incoming directory.

A same-target retry may atomically rematerialize a missing or empty managed
target Compose input only while the durable phase is `prepared` or
`baseline_ready`, canonical/public state still identifies the expected
baseline, the target has an exact staged release record, and no rollback marker
references the target. Non-empty mismatched material, symlinks, owner mismatch,
or any Stage 1 intent fail closed and are never replaced automatically. Both
inputs and the complete staged provenance record are preflighted before either
input is changed, so a corrupt peer cannot leave a partial recovery.

## Operational constraints

- Never run `deploy.yml` while validating repository changes.
- Never use this document as approval for SSH, deployment, migration, secret
  rotation, or production mutation.
- Never use `docker compose down -v`, `docker volume rm`, destructive SQL,
  floating image tags, or a floating target branch.
- The normal `deploy` and `rollback` paths remain available and retain their
  existing contracts.
