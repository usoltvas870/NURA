#!/usr/bin/env python3
"""Fail-closed, exact-bundle controller for the isolated P7 Telegram pilot.

The controller intentionally accepts identities, never shell snippets.  Its
production entry point is invoked only from the bundle materialized by
``release_execution_bundle.py`` at ``controller_sha``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import tarfile
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
PHASES = frozenset({
    "pilot_deploy_intent", "pilot_redis_ready", "pilot_worker_ready",
    "pilot_bot_standby", "pilot_polling_intent", "pilot_polling_active",
    "pilot_verified", "pilot_rollback_intent", "pilot_rollback_verified",
})
PROJECT = "nura_tg"
PILOT_TOKEN_FILE = Path("/opt/nura/secrets/nura_tg/telegram_bot_token")
PILOT_DATABASE_URL_FILE = Path("/opt/nura/secrets/nura_tg/database_url")
AUTHORITATIVE_SECRET_OWNER_IDS = frozenset({0})


class PilotError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise PilotError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path, mode: int | None = None) -> None:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail("unsafe_file")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        fail("unsafe_file_mode")


def read_authoritative_secret(
    path: Path,
    *,
    root: Path = Path("/"),
    owner_ids: frozenset[int] = AUTHORITATIVE_SECRET_OWNER_IDS,
) -> bytes:
    """Open an authoritative fixed secret path without following any link."""
    if not path.is_absolute():
        fail("unsafe_secret_path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, directory_flags)
    try:
        for component in path.parts[1:-1]:
            try:
                child = os.open(component, directory_flags, dir_fd=descriptor)
            except OSError as exc:
                raise PilotError("unsafe_secret_path") from exc
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in owner_ids
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                fail("unsafe_secret_path")
        try:
            secret_fd = os.open(path.name, file_flags, dir_fd=descriptor)
        except OSError as exc:
            raise PilotError("unsafe_secret_path") from exc
        try:
            info = os.fstat(secret_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid not in owner_ids
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                fail("unsafe_secret_path")
            return os.read(secret_fd, info.st_size + 1)
        finally:
            os.close(secret_fd)
    finally:
        os.close(descriptor)


def exact_sha(value: str, name: str) -> None:
    if not SHA.fullmatch(value):
        fail(f"invalid_{name}")


def command(
    *args: str,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    result = subprocess.run(
        args, cwd=cwd, env=environment, capture_output=True, text=True, check=False
    )
    if result.returncode:
        fail("controller_command_failed")


def write_state(root: Path, phase: str, target_sha: str, controller_digest: str) -> None:
    if phase not in PHASES:
        fail("invalid_phase")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = root / ".state.tmp"
    temporary.write_text(json.dumps({"phase": phase, "target_sha": target_sha,
                                     "controller_digest": controller_digest}, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, root / "state.json")


def legacy_token_from_env(path: Path) -> bytes:
    """Parse only one dotenv key; never evaluate the legacy environment file."""
    regular(path)
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if any(marker in raw for marker in ("$(`", "$(", "${", "`", "\\")):
            fail("legacy_token_syntax_invalid")
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        match = re.fullmatch(r"TELEGRAM_BOT_TOKEN\s*=\s*(.*)", line)
        if match is None:
            continue
        value = match.group(1).rstrip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            closing = value.find(quote, 1)
            if closing < 1:
                fail("legacy_token_syntax_invalid")
            decoded = value[1:closing]
            suffix = value[closing + 1:].lstrip()
            if suffix and not suffix.startswith("#"):
                fail("legacy_token_syntax_invalid")
        else:
            decoded = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if not decoded:
            fail("legacy_token_syntax_invalid")
        values.append(decoded)
    if len(values) != 1:
        fail("legacy_token_contract_invalid")
    return values[0].encode("utf-8")


def preflight(repo: Path, controller_sha: str, target_sha: str, expected_host: str,
              controller: Path, token: Path) -> str:
    exact_sha(controller_sha, "controller_sha")
    exact_sha(target_sha, "target_sha")
    if not expected_host or "\n" in expected_host:
        fail("invalid_expected_host")
    regular(controller, 0o600)
    token_value = read_authoritative_secret(token)
    if not token_value or b"\n" in token_value or b"\r" in token_value or b"\x00" in token_value:
        fail("invalid_pilot_token")
    database_url = PILOT_DATABASE_URL_FILE
    database_url_value = read_authoritative_secret(database_url)
    if not database_url_value or b"\n" in database_url_value or b"\r" in database_url_value or b"\x00" in database_url_value:
        fail("invalid_pilot_database_url")
    legacy_env = Path("/opt/nura/nura_app/.env")
    regular(legacy_env)
    legacy_token = legacy_token_from_env(legacy_env)
    if hmac.compare_digest(token_value, legacy_token):
        fail("pilot_legacy_token_contract_failed")
    if sha256(controller) != os.environ.get("NURA_TG_CONTROLLER_DIGEST", ""):
        fail("controller_digest_mismatch")
    result = subprocess.run(["hostname", "-f"], capture_output=True, text=True, check=False)
    if result.returncode or result.stdout.strip() != expected_host:
        fail("production_host_identity_mismatch")
    command("git", "-C", str(repo), "cat-file", "-e", f"{controller_sha}^{{commit}}")
    command("git", "-C", str(repo), "cat-file", "-e", f"{target_sha}^{{commit}}")
    command("git", "-C", str(repo), "merge-base", "--is-ancestor", target_sha, "origin/main")
    return sha256(controller)


def extract_target(repo: Path, target_sha: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", target_sha],
        capture_output=True,
        check=False,
    )
    if archive.returncode:
        fail("target_bundle_unavailable")
    with tarfile.open(fileobj=__import__("io").BytesIO(archive.stdout)) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if member.issym() or path.is_absolute() or ".." in path.parts:
                fail("unsafe_target_bundle")
        bundle.extractall(destination, filter="data")


def docker(*args: str, cwd: Path) -> None:
    command("docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", *args, cwd=cwd)


def resolved_compose(compose: Path, cwd: Path, environment: dict[str, str]) -> None:
    result = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "config", "--format", "json"], cwd=cwd, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        fail("pilot_compose_config_invalid")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PilotError("pilot_compose_config_invalid") from exc
    if set(payload.get("services", {})) != {"redis", "bot", "celery-worker"}:
        fail("pilot_compose_services_forbidden")
    if set(payload.get("volumes", {})) != {"nura_tg_redis_data"}:
        fail("pilot_compose_volumes_forbidden")
    networks = payload.get("networks", {})
    if set(networks) != {"pilot", "legacy_postgres"} or not networks["legacy_postgres"].get("external"):
        fail("pilot_compose_networks_forbidden")


def require_running(app: Path, environment: dict[str, str], service: str) -> None:
    result = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", "ps", "--status", "running", "--services"], cwd=app, env=environment, capture_output=True, text=True, check=False)
    if result.returncode or service not in result.stdout.splitlines():
        fail("pilot_service_not_ready")


def compose_output(app: Path, environment: dict[str, str], *args: str) -> str:
    result = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", *args], cwd=app, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        fail("pilot_runtime_probe_failed")
    return result.stdout


def exec_probe(app: Path, environment: dict[str, str], service: str, *args: str) -> str:
    return compose_output(app, environment, "exec", "-T", service, *args)


def verify_worker(app: Path, environment: dict[str, str]) -> None:
    require_running(app, environment, "celery-worker")
    for secret in ("/run/secrets/telegram_bot_token", "/run/secrets/redis_password"):
        exec_probe(app, environment, "celery-worker", "test", "-r", secret)
    exec_probe(app, environment, "celery-worker", "python", "-m", "core.redis_auth_probe")
    probe = "import asyncio\nfrom core.database import create_engine, get_redis\nasync def p():\n e=create_engine()\n async with e.connect() as c: await c.exec_driver_sql('SELECT 1')\n await e.dispose()\n await get_redis().ping()\nasyncio.run(p())"
    exec_probe(app, environment, "celery-worker", "python", "-c", probe)
    exec_probe(app, environment, "celery-worker", "celery", "-A", "core.tasks", "inspect", "ping")
    queues = exec_probe(app, environment, "celery-worker", "celery", "-A", "core.tasks", "inspect", "active_queues", "--json")
    if '"name": "nura_tg"' not in queues or '"name": "celery"' in queues:
        fail("pilot_worker_queue_contract_failed")
    if "celery beat" in exec_probe(app, environment, "celery-worker", "ps", "-eo", "args"):
        fail("pilot_scheduler_forbidden")


def verify_bot_standby(app: Path, environment: dict[str, str]) -> None:
    require_running(app, environment, "bot")
    exec_probe(app, environment, "bot", "test", "-r", "/run/secrets/telegram_bot_token")
    probe = "import asyncio\nfrom core.database import create_engine, get_redis\nasync def p():\n e=create_engine()\n async with e.connect() as c: await c.exec_driver_sql('SELECT 1')\n await e.dispose()\n await get_redis().ping()\nasyncio.run(p())"
    exec_probe(app, environment, "bot", "python", "-c", probe)
    logs = compose_output(app, environment, "logs", "--no-log-prefix", "bot")
    if "Bot standby ready without polling" not in logs or "Bot polling started" in logs:
        fail("pilot_standby_polling_contract_failed")


def deploy(args: argparse.Namespace) -> None:
    import fcntl
    repo = Path(args.repo).resolve(strict=True)
    controller = Path(__file__).resolve(strict=True)
    token = PILOT_TOKEN_FILE
    digest = preflight(repo, args.controller_sha, args.target_sha, args.expected_host, controller, token)
    state = Path("/var/lib/nura-tg-pilot")
    lock_path = Path("/run/lock/nura-tg-deploy.lock")
    lock_path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        if not fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB):
            fail("pilot_deploy_lock_unavailable")
        write_state(state, "pilot_deploy_intent", args.target_sha, digest)
        legacy_id = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-bot-1"], capture_output=True, text=True, check=False).stdout.strip()
        postgres_id = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-postgres-1"], capture_output=True, text=True, check=False).stdout.strip()
        if not legacy_id or not postgres_id:
            fail("legacy_runtime_preflight_failed")
        app: Path | None = None
        environment: dict[str, str] | None = None
        try:
          with tempfile.TemporaryDirectory(prefix="nura-tg-target-", dir="/var/tmp") as raw:
            target = Path(raw)
            extract_target(repo, args.target_sha, target)
            app = target / "nura_app"
            compose = app / "docker-compose.nura-tg.yml"
            if not compose.is_file() or compose.is_symlink():
                fail("target_compose_missing")
            secret_root = Path("/var/lib/nura-tg-pilot/secrets")
            secret_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            redis_secret = secret_root / "redis_password"
            if not redis_secret.exists():
                redis_secret.write_text(secrets.token_urlsafe(48), encoding="ascii")
                os.chmod(redis_secret, 0o600)
            regular(redis_secret, 0o600)
            environment = os.environ.copy()
            environment.update({
                "NURA_TG_REDIS_SECRET_FILE": str(redis_secret),
                "NURA_TG_POLLING_ENABLED": "false",
            })
            resolved_compose(compose, app, environment)
            subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "up", "-d", "redis"], cwd=app, env=environment, check=True)
            require_running(app, environment, "redis")
            command(
                "docker", "compose", "-p", PROJECT, "-f", str(compose), "exec", "-T",
                "redis", "/bin/sh", "/usr/local/bin/nura-redis-healthcheck",
                cwd=app, environment=environment,
            )
            unauth = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "exec", "-T", "redis", "redis-cli", "ping"], cwd=app, env=environment, capture_output=True, check=False)
            if unauth.returncode == 0:
                fail("pilot_redis_unauthenticated_access")
            write_state(state, "pilot_redis_ready", args.target_sha, digest)
            subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "up", "-d", "celery-worker"], cwd=app, env=environment, check=True)
            verify_worker(app, environment)
            write_state(state, "pilot_worker_ready", args.target_sha, digest)
            subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "up", "-d", "bot"], cwd=app, env=environment, check=True)
            verify_bot_standby(app, environment)
            write_state(state, "pilot_bot_standby", args.target_sha, digest)
            write_state(state, "pilot_polling_intent", args.target_sha, digest)
            environment["NURA_TG_POLLING_ENABLED"] = "true"
            subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(compose), "up", "-d", "--force-recreate", "bot"], cwd=app, env=environment, check=True)
            require_running(app, environment, "bot")
            identity = exec_probe(app, environment, "bot", "hostname").strip()
            lease_probe = "import asyncio\nfrom core.database import get_redis\nasync def p():\n r=get_redis()\n print((await r.get('nura_tg:polling_lease')).decode())\n print(await r.ttl('nura_tg:polling_lease'))\nasyncio.run(p())"
            lease = exec_probe(app, environment, "bot", "python", "-c", lease_probe).splitlines()
            if len(lease) != 2 or lease[0] != identity or not lease[1].isdigit() or int(lease[1]) <= 0:
                fail("pilot_polling_lease_contract_failed")
            marker_probe = "import asyncio\nfrom core.database import get_redis\nasync def p():\n print((await get_redis().get('nura_tg:polling_active')).decode())\nasyncio.run(p())"
            if exec_probe(app, environment, "bot", "python", "-c", marker_probe).strip() != identity:
                fail("pilot_polling_start_unconfirmed")
            if subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-bot-1"], capture_output=True, text=True, check=False).stdout.strip() != legacy_id:
                fail("legacy_bot_changed")
            if subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-postgres-1"], capture_output=True, text=True, check=False).stdout.strip() != postgres_id:
                fail("postgres_changed")
            write_state(state, "pilot_polling_active", args.target_sha, digest)
            write_state(state, "pilot_verified", args.target_sha, digest)
        except Exception as exc:
            write_state(state, "pilot_rollback_intent", args.target_sha, digest)
            if app is not None and environment is not None:
                stopped = subprocess.run(
                    ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", "stop", "bot", "celery-worker"],
                    cwd=app, env=environment, check=False, capture_output=True,
                )
                lease_check = subprocess.run(
                    ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", "exec", "-T", "redis", "redis-cli", "mget", "nura_tg:polling_lease", "nura_tg:polling_active"],
                    cwd=app, env=environment, check=False, capture_output=True, text=True,
                )
                redis_stop = subprocess.run(
                    ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", "stop", "redis"],
                    cwd=app, env=environment, check=False, capture_output=True,
                )
                running = subprocess.run(
                    ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.nura-tg.yml", "ps", "--status", "running", "--services"],
                    cwd=app, env=environment, check=False, capture_output=True, text=True,
                )
                legacy_now = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-bot-1"], capture_output=True, text=True, check=False).stdout.strip()
                postgres_now = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "nura_app-postgres-1"], capture_output=True, text=True, check=False).stdout.strip()
                if stopped.returncode or lease_check.returncode or lease_check.stdout.strip() or redis_stop.returncode or running.returncode or running.stdout.strip() or legacy_now != legacy_id or postgres_now != postgres_id:
                    raise PilotError("pilot_rollback_runtime_unverified") from exc
            write_state(state, "pilot_rollback_verified", args.target_sha, digest)
            raise PilotError("pilot_deploy_rolled_back") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "deploy"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--expected-host", required=True)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            preflight(args.repo.resolve(strict=True), args.controller_sha, args.target_sha,
                      args.expected_host, Path(__file__).resolve(strict=True),
                      PILOT_TOKEN_FILE)
        else:
            deploy(args)
    except PilotError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
