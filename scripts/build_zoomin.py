"""CapCut demo — только Zoom In, через capcut-cli, без Scale X/Y, без Zoom Out."""

import subprocess
import sys
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


def _run(*args: str) -> str:
    result = subprocess.run(
        ["npx.cmd", "capcut-cli", *args],
        capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
    )
    if result.returncode != 0:
        print(f"capcut-cli error: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout


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

    name = f"nura_zoomin_{uuid.uuid4().hex[:6]}"
    dur_sec = _probe_duration(video)

    print(f"1. Init project: {name}")
    result = _run("init", name, "--template", str(TEMPLATE_DIR), "--drafts", str(DRAFTS_DIR))
    project_dir = DRAFTS_DIR / name
    import json
    init_data = json.loads(result)
    new_uuid = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id", "")

    # Rename stale Timeline subdir to new UUID
    import shutil
    tl_dir = project_dir / "Timelines"
    for sub in list(tl_dir.iterdir()):
        if sub.is_dir() and sub.name != new_uuid:
            old_uuid = sub.name
            # Rewrite old UUID → new UUID in all JSON files inside
            for f in sub.rglob("*.json"):
                text = f.read_text("utf-8")
                if old_uuid in text:
                    text = text.replace(old_uuid, new_uuid)
                    f.write_text(text, encoding="utf-8")
            # Rename directory
            dst = tl_dir / new_uuid
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(sub), str(dst))
            print(f"   Renamed timeline {old_uuid[:8]} -> {new_uuid[:8]}")
        elif sub.suffix == ".json":
            pj = json.loads(sub.read_text("utf-8"))
            if pj.get("main_timeline_id") != new_uuid:
                pj["main_timeline_id"] = new_uuid
                sub.write_text(json.dumps(pj, ensure_ascii=False), encoding="utf-8")
                print(f"   Updated {sub.name} main_timeline_id -> {new_uuid[:8]}")

    print(f"2. Add video (full {dur_sec:.1f}s)")
    rel_path = video.relative_to(NURA_ROOT).as_posix()
    _run("add-video", str(project_dir), rel_path, "0", f"{dur_sec:.2f}s")

    # Get segment id
    info = _run("segments", str(project_dir), "--track", "video")
    segs = json.loads(info) if info.strip().startswith("[") else json.loads(info).get("segments", json.loads(info))
    if not segs:
        print("No segments found")
        sys.exit(1)
    seg_id = segs[0].get("id", segs[0].get("segment_id", ""))
    print(f"   Segment ID: {seg_id[:12]}...")

    # Define zoom levels at segment-relative times
    SEG_DUR = min(3.0, dur_sec / 8)
    n_segs = max(1, min(8, int(dur_sec / SEG_DUR)))

    zoom_levels = [
        (1.0, "Original"),
        (1.3, "Zoom In 1.3x"),
        (1.5, "Zoom In 1.5x"),
        (1.8, "Zoom In 1.8x"),
        (2.0, "Zoom In 2.0x"),
        (2.5, "Zoom In 2.5x"),
        (3.0, "Zoom In 3.0x"),
        (1.0, "Reset"),
    ]

    print(f"3. Adding {min(n_segs, len(zoom_levels))} keyframe pairs...")
    for i in range(min(n_segs, len(zoom_levels))):
        t_start = i * SEG_DUR
        t_end = min((i + 1) * SEG_DUR, dur_sec)
        val, label = zoom_levels[i]

        _run("keyframe", str(project_dir), seg_id, "uniform_scale", f"{t_start}s", str(val))
        _run("keyframe", str(project_dir), seg_id, "uniform_scale", f"{t_end}s", str(val))

        # Add text label
        _run(
            "add-text", str(project_dir), f"{t_start}s", f"{t_end - t_start}s", label,
            "--font-size", "18", "--color", "#FF6B00", "--align", "1", "--y", "-0.2",
            "--track-name", "labels",
        )

    print(f"\nProject ready: {project_dir}")
    print(f"Duration: {dur_sec:.1f}s | Segments: {min(n_segs, len(zoom_levels))}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_zoomin.py <video.mp4>")
        sys.exit(1)
    main()
