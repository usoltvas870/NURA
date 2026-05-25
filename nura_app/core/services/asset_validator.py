import json
from dataclasses import dataclass, field
from pathlib import Path

from core.services.video_assembler import NURA_ROOT, _probe_duration

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


@dataclass
class AssetReport:
    job_id: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    missing_files: list[str] = field(default_factory=list)
    corrupt_files: list[str] = field(default_factory=list)
    wrong_resolution: list[str] = field(default_factory=list)
    scenes_missing: list[int] = field(default_factory=list)


def validate_job_assets(
    job_dir: Path,
    scenario_path: Path | None = None,
) -> AssetReport:
    if scenario_path is None:
        scenario_path = job_dir / "input" / "scenario.json"

    report = AssetReport(job_id=job_dir.name)

    if not scenario_path.exists():
        report.passed = False
        report.errors.append(f"Scenario file not found: {scenario_path}")
        return report

    try:
        raw = json.loads(scenario_path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report.passed = False
        report.errors.append(f"Cannot read scenario: {e}")
        return report

    _validate_media_files(job_dir, raw, report)
    _validate_scene_references(job_dir, raw, report)
    _validate_overlay_sources(raw, report)

    return report


def _validate_media_files(
    job_dir: Path,
    scenario: dict,
    report: AssetReport,
) -> None:
    media_dir = job_dir / "media"
    if not media_dir.exists():
        report.warnings.append(f"Media directory not found: {media_dir}")
        return

    nura_video_rel = scenario.get("nura_video", "")
    if nura_video_rel:
        main_video = NURA_ROOT / nura_video_rel
        _check_video_file(main_video, "Nura avatar video", report)

    for i, scene in enumerate(scenario.get("scenes", [])):
        source = scene.get("source")
        if not source:
            continue

        video_path = NURA_ROOT / source
        if not video_path.exists():
            video_path = job_dir / "media" / Path(source).name

        if not video_path.exists():
            report.missing_files.append(f"Scene {i}: {source}")
            report.passed = False
            continue

        _check_video_file(video_path, f"Scene {i} source: {source}", report)


def _check_video_file(path: Path, label: str, report: AssetReport) -> None:
    if not path.exists():
        report.missing_files.append(label)
        report.passed = False
        return

    if path.stat().st_size == 0:
        report.corrupt_files.append(label)
        report.passed = False
        return

    try:
        _probe_duration(path)
    except Exception:
        report.corrupt_files.append(f"{label} — cannot probe duration")
        report.passed = False
        return


def _validate_scene_references(
    job_dir: Path,
    scenario: dict,
    report: AssetReport,
) -> None:
    scenes = scenario.get("scenes", [])
    if not scenes:
        report.warnings.append("No scenes in scenario")
        return

    total_duration = 0.0
    for i, scene in enumerate(scenes):
        dur = scene.get("duration", 0)
        if dur <= 0:
            report.scenes_missing.append(i)
            report.passed = False
        total_duration += dur

    if scenes and total_duration < 5:
        report.warnings.append(f"Total duration very short: {total_duration:.1f}s")

    if scenes and total_duration > 90:
        report.warnings.append(f"Total duration very long: {total_duration:.1f}s")


def _validate_overlay_sources(
    scenario: dict,
    report: AssetReport,
) -> None:
    for i, scene in enumerate(scenario.get("scenes", [])):
        for j, overlay in enumerate(scene.get("overlays", [])):
            ov_type = overlay.get("type", "")
            src = overlay.get("src", "")
            if ov_type in ("video", "image") and src:
                src_path = NURA_ROOT / src
                if not src_path.exists():
                    report.warnings.append(
                        f"Scene {i} overlay {j}: source not found — {src}"
                    )

                if ov_type == "image" and HAS_PILLOW and src_path.exists():
                    try:
                        im = Image.open(src_path)
                        w, h = im.size
                        im.close()
                        if w < 300 or h < 300:
                            report.wrong_resolution.append(
                                f"Scene {i} overlay {j}: low resolution {w}x{h}"
                            )
                    except Exception:
                        report.corrupt_files.append(
                            f"Scene {i} overlay {j} image corrupt: {src}"
                        )
                        report.passed = False


def format_asset_report(report: AssetReport) -> str:
    lines = [f"Asset check for job '{report.job_id}':"]
    lines.append(f"  Status: {'PASSED' if report.passed else 'FAILED'}")

    if report.errors:
        lines.append(f"  Errors ({len(report.errors)}):")
        for e in report.errors:
            lines.append(f"    - {e}")

    if report.missing_files:
        lines.append(f"  Missing files ({len(report.missing_files)}):")
        for f in report.missing_files:
            lines.append(f"    - {f}")

    if report.corrupt_files:
        lines.append(f"  Corrupt files ({len(report.corrupt_files)}):")
        for f in report.corrupt_files:
            lines.append(f"    - {f}")

    if report.wrong_resolution:
        lines.append(f"  Wrong resolution ({len(report.wrong_resolution)}):")
        for f in report.wrong_resolution:
            lines.append(f"    - {f}")

    if report.scenes_missing:
        lines.append(f"  Scenes with zero duration: {report.scenes_missing}")

    if report.warnings:
        lines.append(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    - {w}")

    return "\n".join(lines)
