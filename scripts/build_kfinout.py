"""CapCut — keyframe in/out анимации на одном сегменте (весь ролик)."""

import json
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
        m = __import__("re").search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
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

    name = f"nura_kfinout_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print("1. Copy seed...")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"2. UUID: {old_id[:8]} -> {new_id[:8]}")
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

    print("3. Copy video...")
    local_path = project_dir / "assets" / "video" / video.name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, local_path)

    # Keyframe animation plan (все на одном сегменте, segment-relative time)
    # (time_s, scale) — ключевые точки анимации
    keyframes = [
        (0.0, 1.0),    # Original
        (3.0, 1.0),    # конец Original
        (3.0, 1.0),    # начало Zoom In
        (6.0, 1.8),    # конец Zoom In
        (6.0, 1.8),    # начало Zoom Out
        (9.0, 1.0),    # конец Zoom Out
        (9.0, 1.0),    # начало Pulse
        (10.5, 1.5),   # пик Pulse
        (12.0, 1.0),   # конец Pulse
        (12.0, 1.0),   # начало Zoom In 2.5x
        (15.0, 2.5),   # конец Zoom In
        (15.0, 2.5),   # начало Zoom Out
        (18.0, 1.0),   # конец Zoom Out
        (18.0, 1.0),   # начало Slow Zoom In
        (21.0, 1.3),   # конец Slow Zoom In
        (21.0, 1.3),   # начало Slow Zoom Out
        (24.0, 1.0),   # конец Slow Zoom Out
    ]

    # Для каждого отрезка — текстовая подпись
    labels = [
        (0.0, 3.0, "Original 1.0"),
        (3.0, 6.0, "Zoom In 1→1.8"),
        (6.0, 9.0, "Zoom Out 1.8→1"),
        (9.0, 12.0, "Pulse 1→1.5→1"),
        (12.0, 15.0, "Zoom In 1→2.5"),
        (15.0, 18.0, "Zoom Out 2.5→1"),
        (18.0, 21.0, "Slow In 1→1.3"),
        (21.0, 24.0, "Slow Out 1.3→1"),
    ]

    # Build keyframe lists for each property
    def kf_list(prop, pairs):
        """pairs = [(time_us, value), ...]"""
        return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}

    scale_pairs = [(t, v) for t, v in keyframes]

    # Для Position и Rotation — только start + end, locked
    pos_start = 0
    pos_end = int(dur_sec * 1_000_000)

    common_kfs = [
        kf_list("KFTypePositionX", [(0, 0.0), (dur_sec, 0.0)]),
        kf_list("KFTypePositionY", [(0, 0.0), (dur_sec, 0.0)]),
        kf_list("KFTypeScaleX", scale_pairs),
        kf_list("KFTypeRotation", [(0, 0.0), (dur_sec, 0.0)]),
    ]

    seg_id = uid()
    video_seg = {
        "id": seg_id,
        "material_id": "",
        "raw_segment_id": uid(),
        "target_timerange": {"start": 0, "duration": dur_us},
        "source_timerange": {"start": 0, "duration": dur_us},
        "speed": 1, "volume": 1, "visible": True, "reverse": False,
        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
                 "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0},
                 "transform": {"x": 0.0, "y": 0.0}},
        "render_index": 14000, "track_render_index": 0, "track_attribute": 0,
        "extra_material_refs": [],
        "common_keyframes": common_kfs,
        "keyframe_refs": [],
    }

    video_mat = {
        "id": "", "unique_id": "", "type": "video",
        "duration": dur_us, "path": str(local_path),
        "width": 1920, "height": 1080,
        "material_name": local_path.name, "has_audio": True,
        "check_flag": 7, "source": 0, "source_platform": 0,
        "category_id": "", "category_name": "local",
        "crop": {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                 "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1},
        "crop_ratio": "free", "crop_scale": 1.0,
        "extra_type_option": 0,
        "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
        "matting": {"flag": 0, "path": "", "interactiveTime": [], "has_use_quick_brush": False,
                    "strokes": [], "has_use_quick_eraser": False, "expansion": 0, "feather": 0,
                    "reverse": False, "custom_matting_id": "", "enable_matting_stroke": False},
        "formula_id": "", "video_algorithm": {"algorithms": []},
        "is_unified_beauty_mode": False, "object_locked": None, "smart_motion": None,
        "multi_camera_info": None, "freeze": None, "picture_from": "none",
        "is_text_edit_overdub": False, "is_ai_generate_content": False,
        "aigc_type": "none", "is_copyright": False,
        "beauty_face_preset_infos": [], "beauty_body_preset_id": "",
        "beauty_face_auto_preset": {"preset_id": "", "name": "", "rate_map": "", "scene": ""},
    }

    # Text materials + segments
    text_segments = []
    text_materials = []
    for ts, te, label in labels:
        tmid = uid()
        text_materials.append({
            "id": tmid, "type": "text",
            "content": json.dumps({
                "styles": [{"range": [0, len(label.encode("utf-16-le"))], "size": 16,
                            "bold": True, "italic": False, "underline": False,
                            "fill": {"alpha": 1, "content": {"render_type": "solid",
                                    "solid": {"alpha": 1, "color": [1, 0.42, 0]}}}}],
                "text": label,
            }),
            "duration": int((te - ts) * 1_000_000), "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 16, "text_color": "#FF6B00",
        })
        text_segments.append({
            "id": uid(), "material_id": tmid, "raw_segment_id": uid(),
            "target_timerange": {"start": int(ts * 1_000_000), "duration": int((te - ts) * 1_000_000)},
            "source_timerange": {"start": int(ts * 1_000_000), "duration": int((te - ts) * 1_000_000)},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": -0.2},
                     "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [], "common_keyframes": [], "keyframe_refs": [],
        })

    # Set material_id on video segment
    video_mat["id"] = uid()
    video_seg["material_id"] = video_mat["id"]

    # Build draft
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = dur_us
    dc["tracks"] = [
        {"id": uid(), "type": "video", "name": "video", "attribute": 0,
         "segments": [video_seg], "is_default_name": False, "flag": 0},
        {"id": uid(), "type": "text", "name": "labels", "attribute": 0,
         "segments": text_segments, "is_default_name": False, "flag": 0},
    ]
    dc["materials"]["videos"] = [video_mat]
    dc["materials"]["texts"] = text_materials

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

    print(f"\nProject ready: {project_dir}")
    print(f"Keyframes: {len(scale_pairs)}")
    for t, v in scale_pairs:
        print(f"  {t}s -> scale {v}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_kfinout.py <video.mp4>")
        sys.exit(1)
    main()
