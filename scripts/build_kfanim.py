"""CapCut — только keyframe анимации scale на одном сегменте."""

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

    name = f"nura_kfanim_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()

    print("1. Copy seed 0517...")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"2. Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_uuid(project_dir, old_id, new_id)

    print("3. Copy video to assets...")
    local_path = copy_to_assets(video, project_dir)

    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)
    print(f"4. Setup project (dur={dur_sec:.1f}s)...")

    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    old_tracks = dc.get("tracks", [])

    dc["name"] = name
    dc["duration"] = dur_us

    # Use existing video material from seed
    video_mat = None
    for mat in dc.get("materials", {}).get("videos", []):
        video_mat = mat
        break

    if not video_mat:
        print("ERROR: no video material in seed")
        sys.exit(1)

    video_mat["path"] = str(local_path)
    video_mat["material_name"] = local_path.name
    video_mat["duration"] = dur_us
    video_mat["has_audio"] = True

    # Keep one video segment covering full duration
    seg_id = uid()
    video_seg = {
        "id": seg_id,
        "material_id": video_mat["id"],
        "raw_segment_id": uid(),
        "target_timerange": {"start": 0, "duration": dur_us},
        "source_timerange": {"start": 0, "duration": dur_us},
        "speed": 1, "volume": 1, "visible": True, "reverse": False,
        "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}},
        "render_index": 14000, "track_render_index": 0, "track_attribute": 0,
        "extra_material_refs": [],
        "common_keyframes": [],
        "keyframe_refs": [],
    }

    video_track = {
        "id": uid(),
        "type": "video",
        "name": "video",
        "attribute": 0,
        "segments": [video_seg],
        "is_default_name": False,
        "flag": 0,
    }

    # Clean text materials and tracks — will add via capcut-cli
    dc["materials"]["texts"] = []
    text_track = {
        "id": uid(),
        "type": "text",
        "name": "labels",
        "attribute": 0,
        "segments": [],
        "is_default_name": False,
        "flag": 0,
    }

    dc["tracks"] = [video_track, text_track]
    (project_dir / "draft_content.json").write_text(
        json.dumps(dc, ensure_ascii=False), encoding="utf-8"
    )

    # Timeline subdir
    tl_content = project_dir / "Timelines" / new_id / "draft_content.json"
    if tl_content.exists():
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc["tracks"]
        tldc["materials"] = dc["materials"]
        tldc["duration"] = dc["duration"]
        tldc["name"] = dc["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    # Meta
    meta_path = project_dir / "draft_meta_info.json"
    if meta_path.exists():
        m = json.loads(meta_path.read_text("utf-8"))
        m["draft_id"] = new_id
        m["draft_name"] = name
        m["draft_fold_path"] = str(project_dir).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
        m["tm_duration"] = dur_us
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    # Keyframe animations (segment-relative times = same as project time since seg starts at 0)
    animations = [
        # (label, [(time_s, scale), ...])
        ("Zoom In 1->1.5", [(0, 1.0), (3, 1.5)]),
        ("Zoom Out 1.5->1", [(3, 1.5), (6, 1.0)]),
        ("Pulse 1->1.4->1", [(7, 1.0), (8.5, 1.4), (10, 1.0)]),
    ]

    print("5. Applying keyframe animations...")
    for label, keyframes in animations:
        t_start = keyframes[0][0]
        t_end = keyframes[-1][0]
        dur = t_end - t_start
        print(f"   {label} ({t_start}s-{t_end}s)")

        for t, val in keyframes:
            result = subprocess.run(
                ["npx.cmd", "capcut-cli", "keyframe", str(project_dir), seg_id, "uniform_scale", f"{t}s", str(val)],
                capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
            )
            if result.returncode != 0:
                print(f"      keyframe error at {t}s: {result.stderr.strip()}")

        # Label
        subprocess.run(
            ["npx.cmd", "capcut-cli", "add-text", str(project_dir), f"{t_start}s", f"{dur}s", label,
             "--font-size", "16", "--color", "#FF6B00", "--align", "1", "--y", "-0.2", "--track-name", "labels"],
            capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
        )

    # Sync timeline subdir
    tl_content = project_dir / "Timelines" / new_id / "draft_content.json"
    if tl_content.exists():
        dc_upd = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc_upd["tracks"]
        tldc["materials"] = dc_upd["materials"]
        tldc["duration"] = dc_upd["duration"]
        tldc["name"] = dc_upd["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_kfanim.py <video.mp4>")
        sys.exit(1)
    main()
