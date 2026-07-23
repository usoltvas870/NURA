"""Open the NURA common release lock without following attacker-controlled paths."""
from __future__ import annotations

import argparse
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - production hosts are Linux
    fcntl = None  # type: ignore[assignment]


def fail(message: str) -> None:
    raise SystemExit(f"release-lock: {message}")


def validate_parent(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        fail("unsafe_lock_directory")
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        fail("unsafe_lock_directory")
    if path == Path("/run/lock"):
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o1777:
            fail("unsafe_lock_directory")
        return
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        fail("unsafe_lock_directory")


@contextmanager
def release_lock(path: Path) -> Iterator[int]:
    if fcntl is None:  # pragma: no cover - production hosts are Linux
        fail("posix_lock_unavailable")
    validate_parent(path.parent)
    if path.is_symlink():
        fail("unsafe_lock_file")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        fail("unsafe_lock_file")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            fail("unsafe_lock_file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("release_locked")
        yield descriptor
    finally:
        os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--lock-file", required=True, type=Path)
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def main(argv: Sequence[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        fail("command_required")
    with release_lock(args.lock_file) as descriptor:
        os.dup2(descriptor, 9)
        os.set_inheritable(9, True)
        os.environ["NURA_COMMON_LOCK_FD"] = "9"
        os.execvp(args.command[1], args.command[1:])


if __name__ == "__main__":
    main()
