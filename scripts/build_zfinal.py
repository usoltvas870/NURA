"""CapCut Zoom In demo — копируем seed 0517 + capcut-cli keyframe."""

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
SEED = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0517"
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


def uid() -> str:
    return str(uuid.uuid4()).upper()


def probe_duration(path: Path) -> float:
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


def replace_uuid(project_dir: Path, old_id: str, new_id: str) -> None:
    for f in project_dir.rglob("*.json"):
        text = f.read_text("utf-8")
        if old_id in text:
            text = text.replace(old_id, new_id)
            f.write_text(text, encoding="utf-8")
    tl_old = project_dir / "Timelines" / old_id
    tl_new = project_dir / "Timelines" / new_id
    if tl_old.exists():
        if tl_new.exists():
            shutil.rmtree(tl_new)
        shutil.move(str(tl_old), str(tl_new))


def copy_to_assets(video: Path, project_dir: Path) -> Path:
    dst = project_dir / "assets" / "video" / video.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, dst)
    return dst


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_zfinal_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()

    print(f"1. Copy seed 0517...")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"2. Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_uuid(project_dir, old_id, new_id)

    print(f"3. Copy video to assets...")
    local_path = copy_to_assets(video, project_dir)

    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)
    print(f"4. Update draft_content.json (dur={dur_sec:.1f}s)...")

    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["name"] = name
    dc["duration"] = dur_us

    for t in dc.get("tracks", []):
        if t.get("type") == "video":
            for seg in t.get("segments", []):
                seg["target_timerange"] = {"start": 0, "duration": dur_us}
                seg["source_timerange"] = {"start": 0, "duration": dur_us}
                mat_id = seg.get("material_id")
                if mat_id:
                    for mat in dc.get("materials", {}).get("videos", []):
                        if mat.get("id") == mat_id:
                            mat["path"] = str(local_path)
                            mat["material_name"] = local_path.name
                            mat["duration"] = dur_us
                            mat["width"] = 1920
                            mat["height"] = 1080
                            mat["has_audio"] = True

    (project_dir / "draft_content.json").write_text(
        json.dumps(dc, ensure_ascii=False), encoding="utf-8"
    )

    # Also update timeline subdir
    tl_content = project_dir / "Timelines" / new_id / "draft_content.json"
    if tl_content.exists():
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc["tracks"]
        tldc["materials"] = dc["materials"]
        tldc["duration"] = dc["duration"]
        tldc["name"] = dc["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    # Update meta
    meta_path = project_dir / "draft_meta_info.json"
    if meta_path.exists():
        m = json.loads(meta_path.read_text("utf-8"))
        m["draft_id"] = new_id
        m["draft_name"] = name
        m["draft_fold_path"] = str(project_dir).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
        m["tm_duration"] = dur_us
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    # Get segment ID for keyframes
    seg_id = None
    for t in dc.get("tracks", []):
        if t.get("type") == "video" and t.get("segments"):
            seg_id = t["segments"][0].get("id")
            break
    if not seg_id:
        print("ERROR: no video segment found")
        sys.exit(1)
    print(f"   Segment ID: {seg_id[:12]}...")

    # Apply keyframes via capcut-cli
    print(f"5. Adding zoom in keyframes...")
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

    for i in range(min(n_segs, len(zoom_levels))):
        t_start = i * SEG_DUR
        t_end = min((i + 1) * SEG_DUR, dur_sec)
        val, label = zoom_levels[i]

        # Add keyframe pair (start + end of segment)
        for cmd_prop, cmd_time, cmd_val in [
            ("uniform_scale", f"{t_start}s", str(val)),
            ("uniform_scale", f"{t_end}s", str(val)),
        ]:
            result = subprocess.run(
                ["npx.cmd", "capcut-cli", "keyframe", str(project_dir), seg_id, cmd_prop, cmd_time, cmd_val],
                capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
            )
            if result.returncode != 0:
                print(f"   keyframe error at {cmd_time}: {result.stderr.strip()}")

        # Add text label
        subprocess.run(
            ["npx.cmd", "capcut-cli", "add-text", str(project_dir), f"{t_start}s", f"{t_end - t_start}s", label,
             "--font-size", "18", "--color", "#FF6B00", "--align", "1", "--y", "-0.2", "--track-name", "labels"],
            capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
        )

    # Also update Timeline subdirs after capcut-cli modified root
    tl_content = project_dir / "Timelines" / new_id / "draft_content.json"
    if tl_content.exists():
        dc_updated = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc_updated["tracks"]
        tldc["materials"] = dc_updated["materials"]
        tldc["duration"] = dc_updated["duration"]
        tldc["name"] = dc_updated["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Duration: {dur_sec:.1f}s | Zoom levels: {min(n_segs, len(zoom_levels))}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_zfinal.py <video.mp4>")
        sys.exit(1)
    main()
