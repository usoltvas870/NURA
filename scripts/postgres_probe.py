#!/usr/bin/env python3
"""Run the two audited PostgreSQL probes with a process-local password."""

from __future__ import annotations

import argparse
import os
import re
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping, Sequence


PRODUCTION_PASSWORD_FILE = Path("/opt/nura/secrets/production/postgres_password")
MAX_PASSWORD_BYTES = 16 * 1024
MAX_RESULT_BYTES = 1024
REVISION_RE = re.compile(r"[0-9a-z]{12,32}\Z", re.ASCII)
COUNT_RE = re.compile(r"[0-9]{1,19}\Z", re.ASCII)
PROBE_SQL = {
    "revision": "SELECT version_num FROM alembic_version",
    "snapshot": (
        "SELECT version_num FROM alembic_version; "
        "SELECT count(*) FROM users; "
        "SELECT count(*) FROM guest_profiles; "
        "SELECT count(*) FROM reports; "
        "SELECT count(*) FROM payments; "
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname=current_database() AND pid<>pg_backend_pid()"
    ),
}


class PostgresProbeError(RuntimeError):
    """A bounded probe failure that never contains credentials or DSNs."""


def _identity() -> tuple[int, int] | None:
    get_uid = getattr(os, "geteuid", None)
    get_gid = getattr(os, "getegid", None)
    if get_uid is None or get_gid is None:
        return None
    return get_uid(), get_gid()


def _validate_password(value: str) -> str:
    if (
        not value
        or len(value.encode("utf-8")) > MAX_PASSWORD_BYTES
        or any(character in value for character in ("\n", "\r", "\x00"))
    ):
        raise PostgresProbeError("postgres_probe_password_invalid")
    return value


def _kill_and_wait(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _terminate_windows_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        _kill_and_wait(process)
        return
    if result.returncode:
        _kill_and_wait(process)
        return
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        _kill_and_wait(process)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            _kill_and_wait(process)
    elif os.name == "nt":
        _terminate_windows_process_tree(process)
    else:
        _kill_and_wait(process)


def _run_bounded(
    command: Sequence[str],
    environment: Mapping[str, str],
    *,
    timeout: float = 30,
) -> tuple[int, bytes, bool]:
    """Run a probe without retaining unbounded child output."""

    group_options: dict[str, object] = {}
    if os.name == "posix":
        group_options["start_new_session"] = True
    elif os.name == "nt":
        group_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        command,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        **group_options,
    )
    assert process.stdout is not None
    output = bytearray()
    overflow = threading.Event()
    reader_errors: list[OSError] = []

    def drain_stdout() -> None:
        try:
            while chunk := process.stdout.read(4096):
                remaining = MAX_RESULT_BYTES + 1 - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])
                if len(output) > MAX_RESULT_BYTES and not overflow.is_set():
                    overflow.set()
                    _terminate_process_tree(process)
        except OSError as exc:
            reader_errors.append(exc)
        finally:
            process.stdout.close()

    reader = threading.Thread(target=drain_stdout, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        raise
    finally:
        reader.join(timeout=5)
        if reader.is_alive():
            _terminate_process_tree(process)
            reader.join(timeout=5)
    if reader.is_alive() or reader_errors:
        raise OSError("bounded PostgreSQL probe reader failed")
    return process.returncode, bytes(output), overflow.is_set()


def read_postgres_password(
    path: Path = PRODUCTION_PASSWORD_FILE,
    *,
    allow_legacy_environment: bool = False,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Read one safe password, using legacy environment only if the file is absent."""

    if not path.is_absolute():
        raise PostgresProbeError("postgres_probe_password_path_invalid")
    try:
        unresolved = path.absolute()
        unresolved.lstat()
    except FileNotFoundError:
        if not allow_legacy_environment:
            raise PostgresProbeError("postgres_probe_password_missing") from None
        fallback = (environment if environment is not None else os.environ).get(
            "POSTGRES_PASSWORD"
        )
        if fallback is None:
            raise PostgresProbeError("postgres_probe_password_missing") from None
        return _validate_password(fallback)
    except OSError as exc:
        raise PostgresProbeError("postgres_probe_password_unreadable") from exc

    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise PostgresProbeError("postgres_probe_password_unsafe") from exc
    if unresolved.is_symlink() or resolved != unresolved:
        raise PostgresProbeError("postgres_probe_password_unsafe")

    descriptor: int | None = None
    try:
        descriptor = os.open(
            unresolved,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
        )
        before = os.fstat(descriptor)
        identity = (0, 0) if unresolved == PRODUCTION_PASSWORD_FILE else _identity()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > MAX_PASSWORD_BYTES
            or (
                identity is not None
                and (
                    before.st_uid != identity[0]
                    or before.st_gid != identity[1]
                    or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
                )
            )
        ):
            raise PostgresProbeError("postgres_probe_password_unsafe")
        raw = os.read(descriptor, MAX_PASSWORD_BYTES + 1)
        after = os.fstat(descriptor)
        path_after = unresolved.lstat()
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_mode, before.st_nlink, before.st_uid, before.st_gid, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_uid, after.st_gid, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or (path_after.st_dev, path_after.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise PostgresProbeError("postgres_probe_password_changed")
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PostgresProbeError("postgres_probe_password_invalid") from exc
        return _validate_password(value)
    except PostgresProbeError:
        raise
    except OSError as exc:
        raise PostgresProbeError("postgres_probe_password_unreadable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def run_postgres_probe(
    compose_file: Path,
    mode: str,
    *,
    password_file: Path = PRODUCTION_PASSWORD_FILE,
    allow_legacy_environment: bool = False,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Run one fixed probe; the password exists only in the child environment."""

    query = PROBE_SQL.get(mode)
    if query is None:
        raise PostgresProbeError("postgres_probe_mode_invalid")
    try:
        compose = compose_file.resolve(strict=True)
        metadata = compose_file.lstat()
    except OSError as exc:
        raise PostgresProbeError("postgres_probe_compose_invalid") from exc
    if compose_file.is_symlink() or compose != compose_file.absolute() or not stat.S_ISREG(metadata.st_mode):
        raise PostgresProbeError("postgres_probe_compose_invalid")

    password = read_postgres_password(
        password_file,
        allow_legacy_environment=allow_legacy_environment,
        environment=environment,
    )
    child_environment = dict(environment if environment is not None else os.environ)
    child_environment.pop("POSTGRES_PASSWORD", None)
    child_environment["PGPASSWORD"] = password
    child_environment["PGCONNECT_TIMEOUT"] = "10"
    child_environment["PGOPTIONS"] = "-c statement_timeout=30000"
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(compose.parent),
        "-f",
        str(compose),
        "exec",
        "-T",
        "-e",
        "PGPASSWORD",
        "-e",
        "PGCONNECT_TIMEOUT",
        "-e",
        "PGOPTIONS",
        "postgres",
        "sh",
        "-lc",
        f'exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c {query!r}',
    ]
    try:
        try:
            returncode, raw_output, overflow = _run_bounded(command, child_environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PostgresProbeError("database_revision_probe_failed") from exc
    finally:
        child_environment.pop("PGPASSWORD", None)
        child_environment.pop("PGCONNECT_TIMEOUT", None)
        child_environment.pop("PGOPTIONS", None)
        password = ""
    if returncode or overflow:
        raise PostgresProbeError("database_revision_probe_failed")
    try:
        output = raw_output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PostgresProbeError("database_revision_probe_failed") from exc
    if len(raw_output) > MAX_RESULT_BYTES:
        raise PostgresProbeError("database_revision_probe_failed")
    values = output.splitlines()
    expected_lines = 1 if mode == "revision" else 6
    if (
        len(values) != expected_lines
        or not values
        or REVISION_RE.fullmatch(values[0]) is None
        or (
            mode == "snapshot"
            and any(COUNT_RE.fullmatch(value) is None for value in values[1:])
        )
    ):
        raise PostgresProbeError("database_revision_probe_failed")
    return "\n".join(values)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(PROBE_SQL))
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--password-file", type=Path, default=PRODUCTION_PASSWORD_FILE)
    parser.add_argument("--allow-legacy-environment", action="store_true")
    args = parser.parse_args(argv)
    try:
        output = run_postgres_probe(
            args.compose_file,
            args.mode,
            password_file=args.password_file,
            allow_legacy_environment=args.allow_legacy_environment,
        )
    except PostgresProbeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
