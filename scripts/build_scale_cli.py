"""Build CapCut scale demo via capcut-cli — гарантированно рабочие keyframes."""

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = NURA_ROOT / "videos" / "template"
DRAFTS_DIR = (
    Path.home()
    / "AppData"
    / "Local"
    / "CapCut"
    / "User Data"
    / "Projects"
    / "com.lveditor.draft"
)
CAPCUT_EXE = (
    Path.home()
    / "AppData"
    / "Local"
    / "CapCut"
    / "Apps"
    / "CapCut.exe"
)

SEG_DUR_S = 3.0
N_SEGS = 8


def _run(*args: str) -> dict:
    cmd = ["npx.cmd", "capcut-cli", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=NURA_ROOT,
        shell=True,
    )
    if result.returncode != 0:
        print(f"capcut-cli error: {result.stderr.strip()}")
        print(f"capcut-cli stdout: {result.stdout}")
        sys.exit(1)
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"capcut-cli output (non-json): {result.stdout}")
            return {}
    return {}


def _probe_duration(path: Path) -> float:
    import re
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, shell=True,
        )
        m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            return h * 3600 + mi * 60 + s + ms / 100
    except Exception:
        pass
    return 0.0


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_scale_cli_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    dur_sec = _probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0

    print(f"1. Init project from template...")
    _run("init", name, "--template", str(TEMPLATE_DIR), "--drafts", str(DRAFTS_DIR.parent.parent))

    # Find the actual project dir
    project_dir = DRAFTS_DIR / name
    if not project_dir.exists():
        print(f"Project dir not found: {project_dir}")
        # Try to find it
        candidates = list(DRAFTS_DIR.glob(f"{name}*"))
        if candidates:
            project_dir = candidates[0]
        else:
            sys.exit(1)

    print(f"   Project: {project_dir}")

    print(f"2. Adding video ({video.name})...")
    rel_path = video.as_posix()
    _run("add-video", str(project_dir), rel_path, "0", f"{dur_sec:.2f}s")

    # Get the video segment ID
    info = _run("segments", str(project_dir), "--track", "video")
    segs = info if isinstance(info, list) else info.get("segments", [])
    if not segs:
        print("   No video segments found, trying different track name...")
        info = _run("segments", str(project_dir))
        segs = info if isinstance(info, list) else info.get("segments", [])
    if not segs:
        print("   No segments at all, dumping info:")
        _run("info", str(project_dir))
        sys.exit(1)

    # First segment has the full video
    first_id = segs[0].get("id", segs[0].get("segment_id", ""))
    print(f"   Video segment ID: {first_id[:12] if first_id else 'unknown'}...")

    if not first_id:
        print("   Could not find segment ID")
        sys.exit(1)

    print(f"3. Creating segments with scale effects...")

    # Use trim + shift via capcut-cli to create segments, or
    # better: use keyframe batch to animate scale per-segment.
    #
    # Since capcut-cli doesn't have a "split segment" command,
    # we'll animate scale over the whole duration with pulsed keyframes.

    # Build keyframe batch: for each 3-second segment, set a scale value
    # At each segment boundary, add a keyframe with the desired scale.
    keyframes = []
    labels_data = []
    total_us = int(dur_sec * 1_000_000)

    # Segment definitions: (label, scale_value)
    segments_def = [
        ("Оригинал", 1.0),
        ("Zoom In 1.3x", 1.3),
        ("Zoom Out 0.7x", 0.7),
        ("Scale X 1.5x", 1.5),
        ("Scale Y 1.5x", 1.5),  # Y-only will be separate
        ("Keyframe Zoom In", 1.5),
        ("Keyframe Zoom Out", 0.6),
        ("Keyframe Pulse", 1.4),
    ]

    # For segments 0-4: static scale per segment
    # For segments 5-7: keyframe animation within segment
    time_points = []
    for i in range(N_SEGS):
        t_start = i * SEG_DUR_S
        t_end = min((i + 1) * SEG_DUR_S, dur_sec)
        if t_start >= dur_sec:
            break

        label, scale_val = segments_def[i]

        if i == 0:
            # original — no keyframes needed, skip
            pass
        elif i == 1:
            # Zoom In 1.3x — static, need keyframe at start + end with same val
            keyframes.append({"property": "uniform_scale", "time": f"{t_start}s", "value": "1.3"})
            keyframes.append({"property": "uniform_scale", "time": f"{t_end}s", "value": "1.3"})
        elif i == 2:
            # Zoom Out 0.7x
            keyframes.append({"property": "uniform_scale", "time": f"{t_start}s", "value": "0.7"})
            keyframes.append({"property": "uniform_scale", "time": f"{t_end}s", "value": "0.7"})
        elif i == 3:
            # Scale X 1.5x
            keyframes.append({"property": "scale_x", "time": f"{t_start}s", "value": "1.5"})
            keyframes.append({"property": "scale_y", "time": f"{t_start}s", "value": "1.0"})
            keyframes.append({"property": "scale_x", "time": f"{t_end}s", "value": "1.5"})
            keyframes.append({"property": "scale_y", "time": f"{t_end}s", "value": "1.0"})
        elif i == 4:
            # Scale Y 1.5x
            keyframes.append({"property": "scale_x", "time": f"{t_start}s", "value": "1.0"})
            keyframes.append({"property": "scale_y", "time": f"{t_start}s", "value": "1.5"})
            keyframes.append({"property": "scale_x", "time": f"{t_end}s", "value": "1.0"})
            keyframes.append({"property": "scale_y", "time": f"{t_end}s", "value": "1.5"})
        elif i == 5:
            # Keyframe Zoom In 1 → 1.5
            keyframes.append({"property": "uniform_scale", "time": f"{t_start}s", "value": "1.0"})
            keyframes.append({"property": "uniform_scale", "time": f"{t_end}s", "value": "1.5"})
        elif i == 6:
            # Keyframe Zoom Out 1 → 0.6
            keyframes.append({"property": "uniform_scale", "time": f"{t_start}s", "value": "1.0"})
            keyframes.append({"property": "uniform_scale", "time": f"{t_end}s", "value": "0.6"})
        elif i == 7:
            # Keyframe Pulse 1 → 1.4 → 1
            mid = t_start + (t_end - t_start) / 2
            keyframes.append({"property": "uniform_scale", "time": f"{t_start}s", "value": "1.0"})
            keyframes.append({"property": "uniform_scale", "time": f"{mid}s", "value": "1.4"})
            keyframes.append({"property": "uniform_scale", "time": f"{t_end}s", "value": "1.0"})

        labels_data.append((t_start, t_end, label))

    # Write keyframe batch to temp file and apply
    if keyframes:
        print(f"4. Applying {len(keyframes)} keyframes...")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            fname = f.name
            for kf in keyframes:
                f.write(json.dumps(kf) + "\n")
        _run("keyframe", str(project_dir), first_id, "--batch", f"@{fname}")
        Path(fname).unlink()
        print("   Keyframes applied")

    # Add text labels for each segment
    print(f"5. Adding text labels...")
    for t_start, t_end, label in labels_data:
        dur = t_end - t_start
        _run(
            "add-text", str(project_dir), f"{t_start}s", f"{dur}s", label,
            "--font-size", "18",
            "--color", "#FF6B00",
            "--align", "1",
            "--y", "-0.2",
            "--track-name", "labels",
        )

    print(f"\nProject ready: {project_dir}")
    print(f"Duration: {dur_sec:.1f}s | Segments: {len(labels_data)}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_scale_cli.py <video.mp4>")
        sys.exit(1)
    main()
