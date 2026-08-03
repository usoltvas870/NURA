"""Load the two audited offline modules without importing the ``core`` package."""

from __future__ import annotations

import importlib.util
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType


class OfflineModuleLoadError(RuntimeError):
    """A bounded loader failure that never includes source content."""


_ALLOWED_MODULES = {
    "_nura_offline_config": PurePosixPath("core/config.py"),
    "_nura_offline_prompt_governance": PurePosixPath(
        "core/services/prompt_governance.py"
    ),
}
_PRIVATE_MODULE_NAME = re.compile(r"^_nura_offline_[a-z_]+$")


def _git(
    repo: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise OfflineModuleLoadError("offline_module_git_unavailable") from exc


def _validate_tracked_source(root: Path, source: Path) -> None:
    """Prove the source is the exact regular blob tracked at repository HEAD."""

    repository = root.parent
    top_level = _git(repository, "rev-parse", "--show-toplevel")
    if top_level.returncode:
        raise OfflineModuleLoadError("offline_module_git_identity_invalid")
    try:
        discovered = Path(top_level.stdout.decode("utf-8", "strict").strip()).resolve(
            strict=True
        )
        relative = source.relative_to(discovered).as_posix()
    except (OSError, UnicodeError, ValueError) as exc:
        raise OfflineModuleLoadError("offline_module_git_identity_invalid") from exc
    if discovered != repository.resolve(strict=True):
        raise OfflineModuleLoadError("offline_module_git_identity_invalid")

    tracked = _git(repository, "ls-files", "--error-unmatch", "--", relative)
    worktree_hash = _git(repository, "hash-object", "--", relative)
    tracked_hash = _git(repository, "rev-parse", f"HEAD:{relative}")
    status = _git(
        repository,
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--",
        relative,
    )
    if (
        tracked.returncode
        or worktree_hash.returncode
        or tracked_hash.returncode
        or status.returncode
        or status.stdout
        or worktree_hash.stdout.strip() != tracked_hash.stdout.strip()
    ):
        raise OfflineModuleLoadError("offline_module_source_not_tracked")


def _validated_source(
    app_root: Path,
    *,
    module_name: str,
    relative_path: str,
) -> Path:
    expected = _ALLOWED_MODULES.get(module_name)
    try:
        requested = PurePosixPath(relative_path)
    except (TypeError, ValueError) as exc:
        raise OfflineModuleLoadError("offline_module_identity_invalid") from exc
    if (
        expected is None
        or _PRIVATE_MODULE_NAME.fullmatch(module_name) is None
        or requested != expected
        or requested.is_absolute()
        or any(part in {"", ".", ".."} for part in requested.parts)
    ):
        raise OfflineModuleLoadError("offline_module_identity_invalid")

    try:
        root = app_root.resolve(strict=True)
        root_metadata = root.lstat()
    except OSError as exc:
        raise OfflineModuleLoadError("offline_module_root_invalid") from exc
    if app_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise OfflineModuleLoadError("offline_module_root_invalid")

    candidate = root
    try:
        for part in requested.parts:
            candidate = candidate / part
            metadata = candidate.lstat()
            if candidate.is_symlink():
                raise OfflineModuleLoadError("offline_module_source_unsafe")
        if not stat.S_ISREG(metadata.st_mode):
            raise OfflineModuleLoadError("offline_module_source_unsafe")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except OfflineModuleLoadError:
        raise
    except (OSError, ValueError) as exc:
        raise OfflineModuleLoadError("offline_module_source_unavailable") from exc
    if resolved != candidate:
        raise OfflineModuleLoadError("offline_module_source_unsafe")
    _validate_tracked_source(root, resolved)
    return resolved


def load_offline_module(
    app_root: Path,
    *,
    module_name: str,
    relative_path: str,
) -> ModuleType:
    """Load one exact allowlisted file under ``app_root`` under a private name."""

    source = _validated_source(
        app_root,
        module_name=module_name,
        relative_path=relative_path,
    )
    existing = sys.modules.get(module_name)
    if existing is not None:
        raise OfflineModuleLoadError("offline_module_name_collision")

    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise OfflineModuleLoadError("offline_module_spec_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get(module_name) is module:
            del sys.modules[module_name]
        raise OfflineModuleLoadError("offline_module_execution_failed") from None
    return module
