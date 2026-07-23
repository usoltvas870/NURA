"""Behavioral contracts for the persistent P7B State B owner."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p7b", ROOT / "scripts" / "p7b_rollout.py")
assert spec and spec.loader
p7b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p7b
spec.loader.exec_module(p7b)

TARGET = "a" * 40
BASELINE = "b" * 40
TARGET_ID = "sha256:" + "a" * 64
BASELINE_ID = "sha256:" + "b" * 64
DIGEST = "c" * 64


def directory_link(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        if link.is_symlink():
            link.unlink()
        else:
            os.rmdir(link)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("directory links are unavailable")


class FakeRunner:
    def __init__(
        self,
        *,
        fail_target_up: bool = False,
        fail_smoke: bool = False,
        wrong_live_volume: bool = False,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_target_up = fail_target_up
        self.fail_smoke = fail_smoke
        self.wrong_live_volume = wrong_live_volume

    def __call__(self, command: p7b.Sequence[str]) -> p7b.CommandResult:
        call = tuple(command)
        self.calls.append(call)
        joined = " ".join(call)
        if call[:4] == ("docker", "image", "inspect", "--format"):
            return p7b.CommandResult(0, TARGET_ID + "\n")
        if call[:4] == ("docker", "volume", "inspect", "--format"):
            return p7b.CommandResult(0, call[-1] + "\n")
        if call[:2] == ("docker", "inspect") and "{{json .Mounts}}" in call:
            service = "postgres" if call[-1].endswith("postgres") else "redis"
            name = (
                "wrong_volume"
                if self.wrong_live_volume
                else f"nura_app_{service}_data"
            )
            destination = "/var/lib/postgresql/data" if service == "postgres" else "/data"
            return p7b.CommandResult(
                0,
                json.dumps(
                    [{"Type": "volume", "Name": name, "Destination": destination}]
                ),
            )
        if call[:2] == ("docker", "inspect"):
            baseline = call[-1].startswith("baseline-container-")
            sha = BASELINE if baseline else TARGET
            image_id = BASELINE_ID if baseline else TARGET_ID
            return p7b.CommandResult(
                0,
                f"true|healthy|nura-release:{sha}|{image_id}|{sha}\n",
            )
        if " compose " in f" {joined} " and " ps -q --all " in f" {joined} ":
            prefix = "baseline-" if "baseline-" in joined else ""
            return p7b.CommandResult(0, f"{prefix}container-{call[-1]}\n")
        if " compose " in f" {joined} " and " ps --format json" in f" {joined} ":
            records = [
                json.dumps(
                    {
                        "Service": service,
                        "State": "running",
                        "Health": "healthy"
                        if service in p7b.HEALTH_SERVICES
                        else "",
                    }
                )
                for service in (*p7b.DATA_SERVICES, *p7b.APP_SERVICES)
            ]
            return p7b.CommandResult(0, "\n".join(records))
        if " compose " in f" {joined} " and " config --format json" in f" {joined} ":
            return p7b.CommandResult(
                0,
                json.dumps(
                    {
                        "services": {
                            "postgres": {
                                "volumes": [
                                    {
                                        "type": "volume",
                                        "source": "postgres_data",
                                        "target": "/var/lib/postgresql/data",
                                    }
                                ]
                            },
                            "redis": {
                                "volumes": [
                                    {
                                        "type": "volume",
                                        "source": "redis_data",
                                        "target": "/data",
                                    }
                                ]
                            },
                        },
                        "volumes": {
                            "postgres_data": {"name": "nura_app_postgres_data"},
                            "redis_data": {"name": "nura_app_redis_data"},
                        },
                    }
                ),
            )
        if " compose " in f" {joined} " and " up " in f" {joined} ":
            if self.fail_target_up and "target-" in joined:
                return p7b.CommandResult(1)
            return p7b.CommandResult(0)
        if call[:3] == ("git", "-C", str(call[2])) and "rev-parse" in call:
            return p7b.CommandResult(0, TARGET + "\n")
        if call and call[0] == "git" and "show" in call:
            return p7b.CommandResult(0, "services: {}\n")
        if call and call[0] == "curl":
            return p7b.CommandResult(0, "500" if self.fail_smoke else "400")
        return p7b.CommandResult(0)


@pytest.fixture
def settings(tmp_path: Path) -> p7b.Settings:
    repo = tmp_path / "repo"
    workdir = repo / "nura_app"
    workdir.mkdir(parents=True)
    compose = workdir / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    env = workdir / ".env"
    env.write_text("SECRET=untouched\nAPP_ENV=development\nTEST_MODE=true\n", encoding="utf-8")
    state_root = tmp_path / "release-state"
    p7b_dir = state_root / "p7b"
    releases = tmp_path / "releases"
    baseline_release = releases / BASELINE
    target_release = releases / TARGET
    (baseline_release / "public").mkdir(parents=True)
    (target_release / "public").mkdir(parents=True)
    (baseline_release / "public" / "VERSION").write_text(BASELINE + "\n", encoding="utf-8")
    (target_release / "public" / "VERSION").write_text(TARGET + "\n", encoding="utf-8")
    current = tmp_path / "current"
    directory_link(current, baseline_release)
    canonical = state_root / "current.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(
        json.dumps(
            {
                "schema": 2,
                "sha": BASELINE,
                "status": "successful",
                "static_release_path": str(baseline_release.resolve()),
                "per_service_image_mapping": {
                    service: f"nura-release:{BASELINE}" for service in p7b.APP_SERVICES
                },
                "per_service_image_ids": {
                    service: BASELINE_ID for service in p7b.APP_SERVICES
                },
            }
        ),
        encoding="utf-8",
    )
    release_state = state_root / "releases" / f"{TARGET}.json"
    release_state.parent.mkdir(parents=True)
    release_state.write_text(
        json.dumps(
            {
                "schema": 2,
                "sha": TARGET,
                "status": "staged",
                "static_release_path": str(target_release.resolve()),
                "artifact_sha256": DIGEST,
                "public_manifest_sha256": DIGEST,
                "application_image_tag": f"nura-release:{TARGET}",
                "application_image_id": TARGET_ID,
                "per_service_image_mapping": {
                    service: f"nura-release:{TARGET}" for service in p7b.APP_SERVICES
                },
                "per_service_image_ids": {
                    service: TARGET_ID for service in p7b.APP_SERVICES
                },
                "oci_revision": TARGET,
                "oci_source": "https://github.com/usoltvas870/NURA",
                "oci_created": "2026-07-23T00:00:00Z",
                "migration_delta": False,
                "activation_history": [BASELINE],
            }
        ),
        encoding="utf-8",
    )
    return p7b.Settings(
        TARGET,
        "nura_app",
        workdir,
        compose,
        p7b_dir,
        env,
        canonical,
        state_root / "previous.json",
        current,
        releases,
        tmp_path / "common.lock",
    )


def handoff(settings: p7b.Settings) -> dict[str, object]:
    settings.target_compose.parent.mkdir(parents=True, exist_ok=True)
    settings.target_compose.write_text("services: {}\n", encoding="utf-8")
    settings.target_override.write_bytes(
        p7b.materialized_override(
            {service: f"nura-release:{TARGET}" for service in p7b.APP_SERVICES}
        )
    )
    target_release = settings.releases_directory / TARGET
    return {
        "target_sha": TARGET,
        "expected_baseline_sha": BASELINE,
        "release_path": str(target_release.resolve()),
        "artifact_sha256": DIGEST,
        "manifest_sha256": DIGEST,
        "image_mapping": {
            service: f"nura-release:{TARGET}" for service in p7b.APP_SERVICES
        },
        "image_ids": {service: TARGET_ID for service in p7b.APP_SERVICES},
        "compose_project": "nura_app",
        "working_directory": str(settings.working_directory.resolve()),
        "compose_files": [str(settings.target_compose), str(settings.target_override)],
        "volumes": {
            "redis": "nura_app_redis_data",
            "postgres": "nura_app_postgres_data",
        },
    }


def baseline(settings: p7b.Settings) -> dict[str, object]:
    compose = settings.baseline_compose(BASELINE)
    override = settings.baseline_override(BASELINE)
    compose.parent.mkdir(parents=True, exist_ok=True)
    compose.write_text("services: {}\n", encoding="utf-8")
    override.write_bytes(
        p7b.materialized_override(
            {service: BASELINE_ID for service in p7b.APP_SERVICES}
        )
    )
    release = settings.releases_directory / BASELINE
    return {
        "target_sha": TARGET,
        "previous_sha": BASELINE,
        "release_path": str(release.resolve()),
        "image_mapping": {
            service: f"nura-release:{BASELINE}" for service in p7b.APP_SERVICES
        },
        "image_ids": {service: BASELINE_ID for service in p7b.APP_SERVICES},
        "compose_project": "nura_app",
        "working_directory": str(settings.working_directory.resolve()),
        "compose_files": [str(compose), str(override)],
        "volumes": {
            "redis": "nura_app_redis_data",
            "postgres": "nura_app_postgres_data",
        },
        "canonical_digest": p7b.hashlib.sha256(
            settings.canonical_state.read_bytes()
        ).hexdigest(),
        "public_target": str(release.resolve()),
    }


def seed(settings: p7b.Settings, phase: str = "baseline_ready") -> None:
    p7b.write_record(settings.handoff_file, "handoff", handoff(settings))
    p7b.write_record(settings.baseline_file, "baseline", baseline(settings))
    p7b.transaction(settings, phase)


def test_integrity_envelope_rejects_corruption_and_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    p7b.write_record(path, "handoff", {"target_sha": TARGET})
    value = json.loads(path.read_text(encoding="utf-8"))
    value["payload"]["target_sha"] = BASELINE
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SystemExit, match="handoff_integrity_failed"):
        p7b.read_record(path, "handoff")


def test_atomic_write_rejects_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(SystemExit, match="unsafe_output_path"):
        p7b.atomic_write(link, b"unsafe")
    assert target.read_text(encoding="utf-8") == "safe"


def test_prepare_handoff_is_secret_free_and_does_not_run_compose(
    settings: p7b.Settings,
) -> None:
    runner = FakeRunner()
    args = p7b.parser().parse_args(
        [
            "prepare-handoff",
            "--sha",
            TARGET,
            "--release-path",
            str(settings.releases_directory / TARGET),
            "--image-id",
            TARGET_ID,
            "--artifact-sha256",
            DIGEST,
            "--manifest-sha256",
            DIGEST,
            "--expected-baseline-sha",
            BASELINE,
        ]
    )
    args.runner = runner
    p7b.prepare_handoff(settings, args)
    saved = settings.handoff_file.read_text(encoding="utf-8")
    assert "SECRET" not in saved
    assert "untouched" not in saved
    assert not any(" compose " in f" {' '.join(call)} " for call in runner.calls)
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == "prepared"


def test_handoff_rejects_mutable_or_inconsistent_image_reference(
    settings: p7b.Settings,
) -> None:
    value = handoff(settings)
    value["image_mapping"]["api"] = "nura-release:latest"
    p7b.write_record(settings.handoff_file, "handoff", value)
    with pytest.raises(SystemExit, match="mutable_image_reference"):
        p7b.validate_handoff(settings, FakeRunner())


def test_handoff_rejects_release_path_escape(settings: p7b.Settings) -> None:
    outside = settings.releases_directory.parent / "outside"
    outside.mkdir()
    value = handoff(settings)
    value["release_path"] = str(outside.resolve())
    p7b.write_record(settings.handoff_file, "handoff", value)
    with pytest.raises(SystemExit, match="release_path_outside_root"):
        p7b.validate_handoff(settings, FakeRunner())


def test_bootstrap_materializes_exact_live_baseline_and_volumes(
    settings: p7b.Settings,
) -> None:
    p7b.write_record(settings.handoff_file, "handoff", handoff(settings))
    p7b.transaction(settings, "prepared")
    p7b.bootstrap(settings, FakeRunner())
    saved = p7b.read_record(settings.baseline_file, "baseline")
    assert saved["previous_sha"] == BASELINE
    assert set(saved["image_ids"].values()) == {BASELINE_ID}
    assert Path(saved["compose_files"][0]).is_file()
    assert Path(saved["compose_files"][1]).is_file()
    assert saved["volumes"] == {
        "redis": "nura_app_redis_data",
        "postgres": "nura_app_postgres_data",
    }
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == "baseline_ready"


def test_bootstrap_rejects_canonical_public_mismatch(settings: p7b.Settings) -> None:
    p7b.write_record(settings.handoff_file, "handoff", handoff(settings))
    p7b.transaction(settings, "prepared")
    wrong = settings.releases_directory / TARGET
    directory_link(settings.current_link, wrong)
    with pytest.raises(SystemExit, match="canonical_public_mismatch"):
        p7b.bootstrap(settings, FakeRunner())


def test_bootstrap_rejects_existing_but_unmounted_expected_volume(
    settings: p7b.Settings,
) -> None:
    p7b.write_record(settings.handoff_file, "handoff", handoff(settings))
    p7b.transaction(settings, "prepared")
    with pytest.raises(SystemExit, match="live_volume_identity_mismatch"):
        p7b.bootstrap(settings, FakeRunner(wrong_live_volume=True))


def test_stage1_orders_intent_before_single_mutation_and_verification(
    settings: p7b.Settings,
) -> None:
    seed(settings)
    runner = FakeRunner()
    p7b.stage1(settings, runner)
    state = p7b.read_record(settings.transaction_file, "transaction")
    assert state["phase"] == "stage1_verified"
    up = [call for call in runner.calls if "up" in call]
    assert len(up) == 1
    assert "postgres" not in up[0]
    assert set(p7b.STAGE1_SERVICES).issubset(up[0])
    assert json.loads(settings.canonical_state.read_text())["sha"] == BASELINE
    assert settings.current_link.resolve().name == BASELINE
    assert (settings.releases_directory / BASELINE / "public" / "VERSION").read_text(
        encoding="utf-8"
    ).strip() == BASELINE


def test_stage1_failure_has_exactly_one_p7b_compensation_owner(
    settings: p7b.Settings,
) -> None:
    seed(settings)
    runner = FakeRunner(fail_target_up=True)
    with pytest.raises(SystemExit, match="verification_failed:compose_up"):
        p7b.stage1(settings, runner)
    state = p7b.read_record(settings.transaction_file, "transaction")
    assert state["phase"] == "stage1_compensated"
    assert state["compensation_owner"] == "p7b"
    up = [call for call in runner.calls if "up" in call]
    assert len(up) == 2
    assert "target-" in " ".join(up[0])
    assert "baseline-" in " ".join(up[1])


def test_stage2_changes_only_app_services_and_writes_completion_receipt(
    settings: p7b.Settings,
) -> None:
    seed(settings, "stage1_verified")
    runner = FakeRunner()
    p7b.stage2(settings, runner)
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == "stage2_verified"
    receipt = p7b.read_record(settings.receipt_file, "receipt")
    assert receipt["target_sha"] == TARGET
    assert settings.environment_backup.read_text(encoding="utf-8").startswith(
        "SECRET=untouched"
    )
    assert "APP_ENV=production" in settings.environment_file.read_text(encoding="utf-8")
    up = [call for call in runner.calls if "up" in call]
    assert len(up) == 1
    assert "redis" not in up[0] and "postgres" not in up[0]
    assert set(p7b.APP_SERVICES).issubset(up[0])


def test_stage2_failure_restores_environment_and_previous_runtime(
    settings: p7b.Settings,
) -> None:
    seed(settings, "stage1_verified")
    runner = FakeRunner(fail_target_up=True)
    with pytest.raises(SystemExit, match="verification_failed:compose_up"):
        p7b.stage2(settings, runner)
    assert settings.environment_file.read_text(encoding="utf-8").endswith(
        "TEST_MODE=true\n"
    )
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == (
        "stage2_compensated"
    )


def test_stage2_intent_precedes_environment_mutation_and_crash_recovers(
    settings: p7b.Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed(settings, "stage1_verified")
    original = p7b.edit_environment

    def crash_after_environment(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        raise RuntimeError("injected process boundary")

    monkeypatch.setattr(p7b, "edit_environment", crash_after_environment)
    with pytest.raises(RuntimeError, match="injected process boundary"):
        p7b.stage2(settings, FakeRunner())
    state = p7b.read_record(settings.transaction_file, "transaction")
    assert state["phase"] == "stage2_compensated"
    assert "APP_ENV=development" in settings.environment_file.read_text(
        encoding="utf-8"
    )


def test_webhook_smoke_failure_is_p7b_compensated(settings: p7b.Settings) -> None:
    seed(settings, "stage2_verified")
    settings.environment_file.write_text(
        "SECRET=untouched\nAPP_ENV=production\nTEST_MODE=false\n",
        encoding="utf-8",
    )
    settings.environment_backup.parent.mkdir(parents=True, exist_ok=True)
    settings.environment_backup.write_text(
        "SECRET=untouched\nAPP_ENV=development\nTEST_MODE=true\n",
        encoding="utf-8",
    )
    runner = FakeRunner(fail_smoke=True)
    with pytest.raises(SystemExit, match="malformed_webhook_smoke_failed"):
        try:
            with p7b.rollout_lock(settings.lock_file):
                p7b.smoke_webhook(
                    settings,
                    runner,
                    "http://127.0.0.1:8000/api/v1/payment/webhook",
                )
        except BaseException:
            with p7b.rollout_lock(settings.lock_file):
                p7b.compensate(settings, runner, 2)
            raise
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == (
        "stage2_compensated"
    )
    assert "APP_ENV=development" in settings.environment_file.read_text(
        encoding="utf-8"
    )


def test_readiness_failure_compensates_verified_stage1(
    settings: p7b.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(settings)
    runner = FakeRunner()

    def failed_readiness(*args: object, **kwargs: object) -> None:
        p7b.fail("verification_failed:readiness_compose_status")

    monkeypatch.setattr(p7b, "readiness", failed_readiness)
    with pytest.raises(SystemExit, match="verification_failed:readiness_compose_status"):
        p7b.activate(
            settings,
            runner,
            "http://127.0.0.1:8000/api/v1/payment/webhook",
        )
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == (
        "stage1_compensated"
    )
    up = [call for call in runner.calls if "up" in call]
    assert len(up) == 2
    assert "target-" in " ".join(up[0])
    assert "baseline-" in " ".join(up[1])


def verified_stage2(settings: p7b.Settings, runner: FakeRunner) -> None:
    seed(settings, "stage2_intent")
    settings.environment_file.write_text(
        "SECRET=untouched\nAPP_ENV=production\nTEST_MODE=false\n",
        encoding="utf-8",
    )
    p7b.verify_stage(settings, 2, runner)
    p7b.transaction(settings, "smoke_verified")


def test_finalize_requires_receipt_then_atomically_advances_markers(
    settings: p7b.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(p7b, "atomic_symlink", directory_link)
    runner = FakeRunner()
    old_sha = "d" * 40
    old_release = settings.releases_directory / old_sha
    old_release.mkdir()
    old_record = settings.canonical_state.parent / "releases" / f"{old_sha}.json"
    old_record.write_text(json.dumps({"sha": old_sha, "legacy": False}), encoding="utf-8")
    verified_stage2(settings, runner)
    p7b.finalize(settings, runner)
    canonical = json.loads(settings.canonical_state.read_text(encoding="utf-8"))
    previous = json.loads(settings.previous_state.read_text(encoding="utf-8"))
    assert canonical["sha"] == TARGET
    assert previous["sha"] == BASELINE
    assert json.loads(settings.release_state_file.read_text())["status"] == "successful"
    assert settings.current_link.resolve().name == TARGET
    assert p7b.read_record(settings.transaction_file, "transaction")["phase"] == "complete"
    assert not old_release.exists()
    assert settings.releases_directory.joinpath(BASELINE).exists()
    assert any(call[-2:] == ("rm", f"nura-release:{old_sha}") for call in runner.calls)
    p7b.finalize(settings, runner)


def test_finalize_recovers_after_partial_marker_switch(
    settings: p7b.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(p7b, "atomic_symlink", directory_link)
    runner = FakeRunner()
    verified_stage2(settings, runner)
    p7b.atomic_write(
        settings.previous_state,
        p7b.canonical_json(p7b.load_canonical(settings)) + b"\n",
        mode=0o640,
    )
    p7b.transaction(settings, "finalizing", previous_saved=True)
    directory_link(settings.current_link, settings.releases_directory / TARGET)
    p7b.recover(settings, runner)
    assert json.loads(settings.canonical_state.read_text())["sha"] == TARGET
    assert json.loads(settings.previous_state.read_text())["sha"] == BASELINE


def test_finalize_validates_release_provenance_before_switching_public_marker(
    settings: p7b.Settings,
) -> None:
    runner = FakeRunner()
    verified_stage2(settings, runner)
    (settings.releases_directory / TARGET / "public" / "VERSION").write_text(
        "wrong-target\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="active_version_mismatch"):
        p7b.finalize(settings, runner)
    assert settings.current_link.resolve().name == BASELINE
    assert json.loads(settings.canonical_state.read_text(encoding="utf-8"))["sha"] == BASELINE


def test_lock_is_nonblocking_and_process_death_safe(settings: p7b.Settings) -> None:
    with p7b.rollout_lock(settings.lock_file):
        with pytest.raises(SystemExit, match="rollout_locked"):
            with p7b.rollout_lock(settings.lock_file):
                pass
    with p7b.rollout_lock(settings.lock_file):
        pass


def test_activation_requires_host_wide_common_lock(settings: p7b.Settings) -> None:
    seed(settings)
    runner = FakeRunner()
    with p7b.rollout_lock(settings.common_lock_file):
        with pytest.raises(SystemExit, match="rollout_locked"):
            p7b.activate(
                settings,
                runner,
                "http://127.0.0.1:8000/api/v1/payment/webhook",
            )
    assert not any(" up " in f" {' '.join(call)} " for call in runner.calls)


def test_source_has_no_destructive_or_secret_dump_commands() -> None:
    source = (ROOT / "scripts" / "p7b_rollout.py").read_text(encoding="utf-8")
    forbidden = (
        "docker compose down",
        "docker volume rm",
        "DROP TABLE",
        "Config.Env",
        "printenv",
        "reset --hard",
        "git clean",
    )
    assert not any(value in source for value in forbidden)
    assert "compensation_owner" in source
    assert "p7b_completion_receipt" in source
