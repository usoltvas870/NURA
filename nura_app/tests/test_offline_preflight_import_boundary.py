"""Import-boundary proof for the minimal production preflight tooling closure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tools.offline_module_loader import OfflineModuleLoadError, load_offline_module


APP_ROOT = Path(__file__).resolve().parents[1]


def test_preflight_import_does_not_initialize_core_or_runtime_packages() -> None:
    script = r"""
import importlib.abc
import json
import os
import pathlib
import sys

app_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(app_root))
os.environ["NURA_DISABLE_DOTENV"] = "1"
os.environ["APP_ENV"] = "development"
for name in tuple(sys.modules):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

forbidden_roots = {"redis", "sqlalchemy", "asyncpg", "celery", "aiogram"}
forbidden_modules = {
    "core.database",
    "core.models",
    "core.repositories",
    "core.services.ai",
    "core.services.payment",
    "core.services.report",
}
attempts = []

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden_roots or fullname in forbidden_modules:
            attempts.append(fullname)
            raise AssertionError("runtime dependency import attempted")
        return None

sys.meta_path.insert(0, Blocker())
import tools.current_vps_prelaunch_preflight as preflight

assert not attempts
assert "core" not in sys.modules
assert "core.database" not in sys.modules
assert "core.repositories" not in sys.modules
assert "redis" not in sys.modules
assert "sqlalchemy" not in sys.modules
assert pathlib.Path(preflight.OFFLINE_CONFIG_MODULE.__file__).resolve() == app_root / "core/config.py"
assert pathlib.Path(preflight.OFFLINE_PROMPT_GOVERNANCE_MODULE.__file__).resolve() == app_root / "core/services/prompt_governance.py"
assert preflight.Settings(_env_file=None).app_env == "development"
assert preflight.prompt_registry.resolve("report.full", "v1").bundle_version == "v1"
print(json.dumps({"status": "PASS", "runtime_import_attempts": attempts}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(APP_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "runtime_import_attempts": [],
        "status": "PASS",
    }


def test_transition_validation_import_remains_stdlib_only() -> None:
    script = r"""
import importlib.abc
import importlib.util
import pathlib
import sys

app_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
engine_path = app_root.parent / "scripts/current_vps_prelaunch_transition.py"
sys.path.insert(0, str(app_root))
forbidden = {
    "pydantic",
    "pydantic_settings",
    "yaml",
    "redis",
    "sqlalchemy",
    "asyncpg",
    "celery",
    "aiogram",
}
attempts = []

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden:
            attempts.append(fullname)
            raise AssertionError("non-stdlib transition validation import attempted")
        return None

sys.meta_path.insert(0, Blocker())
spec = importlib.util.spec_from_file_location("_nura_transition_import_proof", engine_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert not attempts
assert "tools.current_vps_prelaunch_preflight" not in sys.modules
print("PASS")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(APP_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def test_documented_direct_preflight_entrypoint_bootstraps_tools_package() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(APP_ROOT / "tools" / "current_vps_prelaunch_preflight.py"),
            "--help",
        ],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NURA_DISABLE_DOTENV": "1", "APP_ENV": "development"},
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_transition_rejects_checkout_before_importing_preflight() -> None:
    script = r"""
import importlib.util
import pathlib
import sys
import types

app_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
engine_path = app_root.parent / "scripts/current_vps_prelaunch_transition.py"
sys.path.insert(0, str(app_root))
spec = importlib.util.spec_from_file_location("_nura_transition_order_proof", engine_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.validate_authorization_manifest = lambda *args, **kwargs: {}
module._validate_resume_cli_paths = lambda *args, **kwargs: None

def reject_checkout(*args, **kwargs):
    raise module.TransitionError("execution_checkout_dirty")

module.validate_execution_checkout = reject_checkout
sys.modules.pop("tools.current_vps_prelaunch_preflight", None)
args = types.SimpleNamespace(repo=app_root.parent, manifest=app_root / "unused.json")
try:
    module.execute_from_cli(args)
except module.TransitionError as exc:
    assert str(exc) == "execution_checkout_dirty"
else:
    raise AssertionError("dirty checkout was accepted")
assert "tools.current_vps_prelaunch_preflight" not in sys.modules
print("PASS")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(APP_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def _module_tree(root: Path, source: str = "VALUE = 1\n") -> tuple[Path, Path]:
    repository = root / "repo"
    app_root = repository / "nura_app"
    path = app_root / "core" / "config.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", "nura_app/core/config.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=NURA Test",
            "-c",
            "user.email=nura-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    return app_root, path


def test_loader_rejects_path_escape(tmp_path: Path) -> None:
    app_root, _path = _module_tree(tmp_path)
    with pytest.raises(OfflineModuleLoadError, match="offline_module_identity_invalid"):
        load_offline_module(
            app_root,
            module_name="_nura_offline_config",
            relative_path="../config.py",
        )


def test_loader_rejects_missing_file_with_bounded_error(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(OfflineModuleLoadError) as raised:
        load_offline_module(
            tmp_path,
            module_name="_nura_offline_config",
            relative_path="core/config.py",
        )
    assert str(raised.value) == "offline_module_source_unavailable"
    assert str(tmp_path) not in str(raised.value)


def test_loader_rejects_symlink_source(tmp_path: Path) -> None:
    real_directory = tmp_path / "real-core"
    real_directory.mkdir()
    (real_directory / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
    source_directory = tmp_path / "core"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(source_directory), str(real_directory)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        os.symlink(real_directory, source_directory)
    with pytest.raises(OfflineModuleLoadError, match="offline_module_source_unsafe"):
        load_offline_module(
            tmp_path,
            module_name="_nura_offline_config",
            relative_path="core/config.py",
        )


def test_loader_masks_source_content_on_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "fixture-secret-marker-must-not-escape"
    app_root, _path = _module_tree(tmp_path, f"{marker!r} +\n")
    monkeypatch.delitem(sys.modules, "_nura_offline_config", raising=False)
    with pytest.raises(OfflineModuleLoadError) as raised:
        load_offline_module(
            app_root,
            module_name="_nura_offline_config",
            relative_path="core/config.py",
        )
    assert str(raised.value) == "offline_module_execution_failed"
    assert marker not in str(raised.value)


def test_loader_rejects_dirty_tracked_source_before_execution(tmp_path: Path) -> None:
    app_root, path = _module_tree(tmp_path)
    marker = tmp_path / "executed"
    path.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('unsafe')\n",
        encoding="utf-8",
    )
    sys.modules.pop("_nura_offline_config", None)
    with pytest.raises(OfflineModuleLoadError, match="offline_module_source_not_tracked"):
        load_offline_module(
            app_root,
            module_name="_nura_offline_config",
            relative_path="core/config.py",
        )
    assert not marker.exists()


def test_loader_rejects_fake_private_module_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("_nura_offline_config")
    fake.__file__ = str(APP_ROOT / "core" / "config.py")
    monkeypatch.setitem(sys.modules, "_nura_offline_config", fake)
    with pytest.raises(OfflineModuleLoadError, match="offline_module_name_collision"):
        load_offline_module(
            APP_ROOT,
            module_name="_nura_offline_config",
            relative_path="core/config.py",
        )
