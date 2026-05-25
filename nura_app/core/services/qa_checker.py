import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QAResult:
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    video_playable: bool = False
    has_audio: bool = False
    duration_sec: float = 0.0
    resolution: str = ""
    bitrate_kbps: int = 0
    subtitle_count: int = 0


def check_video_output(video_path: Path) -> QAResult:
    result = QAResult()

    if not video_path.exists():
        result.passed = False
        result.errors.append(f"Video file not found: {video_path}")
        return result

    if video_path.stat().st_size == 0:
        result.passed = False
        result.errors.append("Video file is empty (0 bytes)")
        return result

    try:
        probe = _ffprobe_json(video_path)
    except Exception as e:
        result.passed = False
        result.errors.append(f"ffprobe failed: {e}")
        return result

    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    result.video_playable = len(video_streams) > 0
    result.has_audio = len(audio_streams) > 0
    result.subtitle_count = len(subtitle_streams)

    if not result.video_playable:
        result.passed = False
        result.errors.append("No video stream found — file may be corrupt")

    if not result.has_audio:
        result.warnings.append("No audio stream — video may be silent")

    if video_streams:
        vs = video_streams[0]
        w = vs.get("width", 0)
        h = vs.get("height", 0)
        result.resolution = f"{w}x{h}"
        if w < 360 or h < 640:
            result.warnings.append(f"Low resolution: {result.resolution}")

    result.duration_sec = float(fmt.get("duration", 0))
    result.bitrate_kbps = int(int(fmt.get("bit_rate", 0)) / 1000)

    if result.duration_sec < 5:
        result.warnings.append(f"Very short duration: {result.duration_sec:.1f}s")

    if result.bitrate_kbps > 0 and result.bitrate_kbps < 500:
        result.warnings.append(f"Low bitrate: {result.bitrate_kbps} kbps")

    return result


def check_carousel_output(output_dir: Path) -> QAResult:
    result = QAResult()

    if not output_dir.exists():
        result.passed = False
        result.errors.append(f"Carousel output dir not found: {output_dir}")
        return result

    pngs = sorted(output_dir.glob("*.png"))
    if not pngs:
        result.passed = False
        result.errors.append("No PNG files in carousel output")
        return result

    result.subtitle_count = len(pngs)

    try:
        from PIL import Image
    except ImportError:
        result.warnings.append("Pillow not installed — skipping image validation")
        return result

    for p in pngs:
        if p.stat().st_size == 0:
            result.errors.append(f"Empty PNG: {p.name}")
            result.passed = False
            continue

        try:
            im = Image.open(p)
            w, h = im.size
            im.close()
            if w < 500 or h < 500:
                result.warnings.append(f"Low resolution: {p.name} ({w}x{h})")
        except Exception:
            result.errors.append(f"Corrupt image: {p.name}")
            result.passed = False

    return result


def _ffprobe_json(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    proc.check_returncode()
    return json.loads(proc.stdout)


def format_qa_result(result: QAResult, label: str = "Video") -> str:
    lines = [f"QA check for {label}:"]
    lines.append(f"  Status: {'PASSED' if result.passed else 'FAILED'}")
    lines.append(f"  Playable: {result.video_playable}")
    lines.append(f"  Audio: {result.has_audio}")
    lines.append(f"  Duration: {result.duration_sec:.1f}s")
    if result.resolution:
        lines.append(f"  Resolution: {result.resolution}")
    if result.bitrate_kbps:
        lines.append(f"  Bitrate: {result.bitrate_kbps} kbps")
    if result.subtitle_count:
        lines.append(f"  Subtitles/slides: {result.subtitle_count}")

    if result.errors:
        lines.append(f"  Errors ({len(result.errors)}):")
        for e in result.errors:
            lines.append(f"    - {e}")

    if result.warnings:
        lines.append(f"  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            lines.append(f"    - {w}")

    return "\n".join(lines)
