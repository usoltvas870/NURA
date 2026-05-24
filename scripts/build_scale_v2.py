"""Build CapCut scale demo — hybrid: JSON for structure + capcut-cli for keyframes."""

import json
import shutil
import subprocess
import sys
import tempfile
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

SEG_DUR_US = 3_000_000
SEG_DUR_S = 3.0


def uid() -> str:
    return str(uuid.uuid4()).upper()


def uid_hex() -> str:
    return uuid.uuid4().hex


def probe_duration(path: Path) -> float:
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


def replace_uuid(project_dir: Path, old_id: str, new_id: str) -> None:
    for f in project_dir.rglob("*.json"):
        text = f.read_text("utf-8")
        if old_id in text:
            text = text.replace(old_id, new_id)
            f.write_text(text, encoding="utf-8")
    tl_old = project_dir / "Timelines" / old_id
    tl_new = project_dir / "Timelines" / new_id
    if tl_old.exists():
        shutil.move(str(tl_old), str(tl_new))


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_scale_v2_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()

    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    n_segs = max(1, min(8, int(dur_sec * 1_000_000 / SEG_DUR_US)))
    actual_dur = n_segs * SEG_DUR_S

    print(f"Copying seed (0517)...")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_uuid(project_dir, old_id, new_id)

    assets_dir = project_dir / "assets" / "video"
    assets_dir.mkdir(parents=True, exist_ok=True)
    local_path = assets_dir / video.name
    shutil.copy2(video, local_path)

    # --- Build video materials (one per segment, all ref same file) ---
    video_materials = []
    for i in range(n_segs):
        mat_id = uid()
        mat = {
            "id": mat_id, "path": str(local_path), "material_name": video.name,
            "type": "video", "duration": SEG_DUR_US * 3,
            "width": 1920, "height": 1080,
            "category_id": "", "category_name": "local", "check_flag": 7,
            "crop": {"lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1, "upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0},
            "has_audio": True, "extra_type_option": 0, "formula_id": "", "freeze": None,
            "intensifies_audio_path": "", "intensifies_path": "",
            "is_ai_generate_content": False, "is_copyright": False,
            "is_text_edit_overdub": False, "is_unified_beauty_mode": False,
            "local_id": "", "local_material_id": "", "material_url": "",
            "media_path": "", "object_locked": None, "origin_material_id": "",
            "request_id": "", "reverse_path": "", "source_platform": 0,
            "stable": {"matrix_path": "", "stable_level": 0, "time_range": {"duration": 0, "start": 0}},
            "team_id": "",
            "video_algorithm": {"algorithms": [], "deflicker": None, "motion_blur_config": None, "noise_reduction": None, "path": "", "quality_enhance": None, "time_range": None},
        }
        video_materials.append(mat)

    # --- Build segments ---
    scale_segments_def = [
        ("Original",            None),
        ("Zoom In 1.3x",        "uniform_scale 1.3"),
        ("Zoom Out 0.7x",       "uniform_scale 0.7"),
        ("Scale X 1.5x",        "scale_x 1.5"),
        ("Scale Y 1.5x",        "scale_y 1.5"),
        ("Keyframe Zoom In",    "keyframe_uniform_1.5"),
        ("Keyframe Zoom Out",   "keyframe_uniform_0.6"),
        ("Keyframe Pulse",      "keyframe_pulse"),
    ]

    segments = []
    kf_batch = []  # (seg_id, property, time_s, value)

    for i in range(n_segs):
        seg_id = uid()
        mat_id = video_materials[i]["id"]
        start = i * SEG_DUR_US
        src_start = min(i * SEG_DUR_US, int(dur_sec * 1_000_000) - SEG_DUR_US)

        label, scale_rule = scale_segments_def[i]

        clip = {
            "alpha": 1, "rotation": 0,
            "scale": {"x": 1, "y": 1},
            "transform": {"x": 0, "y": 0},
            "flip": {"horizontal": False, "vertical": False},
        }

        if scale_rule:
            parts = scale_rule.split()
            if parts[0] == "uniform_scale":
                clip["scale"]["x"] = float(parts[1])
                clip["scale"]["y"] = float(parts[1])
            elif parts[0] == "scale_x":
                clip["scale"]["x"] = float(parts[1])
            elif parts[0] == "scale_y":
                clip["scale"]["y"] = float(parts[1])

        seg = {
            "id": seg_id,
            "material_id": mat_id,
            "raw_segment_id": uid(),
            "target_timerange": {"start": start, "duration": SEG_DUR_US},
            "source_timerange": {"start": src_start, "duration": SEG_DUR_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": clip,
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [],
            "common_keyframes": [],
            "keyframe_refs": [],
        }

        # Plan keyframes for capcut-cli
        t_start = i * SEG_DUR_S
        t_end = min((i + 1) * SEG_DUR_S, actual_dur)

        if scale_rule == "keyframe_uniform_1.5":
            kf_batch.append((seg_id, "uniform_scale", t_start, 1.0))
            kf_batch.append((seg_id, "uniform_scale", t_end, 1.5))
        elif scale_rule == "keyframe_uniform_0.6":
            kf_batch.append((seg_id, "uniform_scale", t_start, 1.0))
            kf_batch.append((seg_id, "uniform_scale", t_end, 0.6))
        elif scale_rule == "keyframe_pulse":
            mid = t_start + (t_end - t_start) / 2
            kf_batch.append((seg_id, "uniform_scale", t_start, 1.0))
            kf_batch.append((seg_id, "uniform_scale", mid, 1.4))
            kf_batch.append((seg_id, "uniform_scale", t_end, 1.0))

        segments.append((seg, label))

    # Build video track
    video_track = {
        "id": uid(),
        "type": "video",
        "name": "video",
        "attribute": 0,
        "segments": [s[0] for s in segments],
        "is_default_name": False,
        "flag": 0,
    }

    # Build text track
    text_track = {
        "id": uid(),
        "type": "text",
        "name": "labels",
        "attribute": 0,
        "segments": [],
        "is_default_name": False,
        "flag": 0,
    }
    text_materials = []
    for i, (seg, label) in enumerate(segments):
        start = i * SEG_DUR_US
        tmat_id = uid()
        text_materials.append({
            "id": tmat_id,
            "type": "text",
            "content": json.dumps({
                "styles": [{
                    "range": [0, len(label.encode("utf-16-le"))],
                    "size": 18, "bold": True, "italic": False, "underline": False,
                    "fill": {"alpha": 1, "content": {"render_type": "solid", "solid": {"alpha": 1, "color": [1, 0.42, 0]}}},
                }],
                "text": label,
            }),
            "duration": SEG_DUR_US,
            "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 18, "text_color": "#FF6B00",
        })
        text_track["segments"].append({
            "id": uid(),
            "material_id": tmat_id,
            "raw_segment_id": text_track["id"],
            "target_timerange": {"start": start, "duration": SEG_DUR_US},
            "source_timerange": {"start": start, "duration": SEG_DUR_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": -0.2}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [],
            "common_keyframes": [], "keyframe_refs": [],
        })

    # Write draft_content.json
    content_path = project_dir / "draft_content.json"
    dc = json.loads(content_path.read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = int(actual_dur * 1_000_000)
    dc["tracks"] = [video_track, text_track]
    dc["materials"]["videos"] = video_materials
    dc["materials"]["texts"] = text_materials
    content_path.write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    # Also write to Timeline subdir
    tl_dir = project_dir / "Timelines" / new_id
    if tl_dir.exists():
        tl_content = tl_dir / "draft_content.json"
        if tl_content.exists():
            tl_dc = json.loads(tl_content.read_text("utf-8"))
            tl_dc["tracks"] = dc["tracks"]
            tl_dc["materials"] = dc["materials"]
            tl_dc["duration"] = dc["duration"]
            tl_dc["name"] = dc["name"]
            tl_content.write_text(json.dumps(tl_dc, ensure_ascii=False), encoding="utf-8")

    # Update meta
    meta_path = project_dir / "draft_meta_info.json"
    if meta_path.exists():
        m = json.loads(meta_path.read_text("utf-8"))
        m["draft_id"] = new_id
        m["draft_name"] = name
        m["draft_fold_path"] = str(project_dir).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    # --- Apply keyframes via capcut-cli (single-shot, batch mode broken on Windows) ---
    if kf_batch:
        from collections import defaultdict
        by_seg = defaultdict(list)
        for seg_id, prop, t, val in kf_batch:
            by_seg[seg_id].append((prop, f"{t}s", str(val)))

        total = sum(len(v) for v in by_seg.values())
        print(f"Applying {total} keyframes to {len(by_seg)} segments (single-shot)...")
        for seg_id, entries in by_seg.items():
            for prop, t_str, val_str in entries:
                result = subprocess.run(
                    ["npx.cmd", "capcut-cli", "keyframe", str(project_dir), seg_id, prop, t_str, val_str],
                    capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
                )
                if result.returncode != 0:
                    print(f"  seg {seg_id[:8]} {prop}@{t_str}={val_str}: {result.stderr.strip()}")
            print(f"  seg {seg_id[:8]}: {len(entries)} keyframes OK")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {len(segments)}, total: {actual_dur:.0f}s")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_scale_v2.py <video.mp4>")
        sys.exit(1)
    main()
