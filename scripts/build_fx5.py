"""CapCut — все эффекты, мульти-сегмент (как build_zoom_kf.py) с правильными KFType*."""

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
SEED = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0517"
DRAFTS_DIR = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
CAPCUT_EXE = Path.home() / "AppData/Local/CapCut/Apps/CapCut.exe"


def uid() -> str:
    return str(uuid.uuid4()).upper()


def probe_duration(path: Path) -> float:
    try:
        import imageio_ffmpeg
        fm = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([fm, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, shell=True)
        m = __import__("re").search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            return h * 3600 + mi * 60 + s + ms / 100
    except Exception:
        pass
    return 0.0


def make_video_mat(mid: str, path: Path, dur_us: int) -> dict:
    return {"id": mid, "type": "video", "duration": dur_us, "path": str(path),
            "material_name": path.name, "width": 1920, "height": 1080, "has_audio": True, "check_flag": 7,
            "crop": {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                     "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1},
            "crop_ratio": "free", "crop_scale": 1, "extra_type_option": 0,
            "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
            "matting": {"flag": 0}, "source": 0, "source_platform": 0, "formula_id": "",
            "video_algorithm": {"algorithms": []},
            "is_unified_beauty_mode": False, "object_locked": None, "freeze": None,
            "is_ai_generate_content": False, "is_copyright": False}


def make_kf(prop: str, pairs: list) -> dict:
    return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}


def lock_kfs(dur_s: float, extra: dict | None = None) -> list:
    base = {
        "KFTypePositionX": [(0, 0.0), (dur_s, 0.0)],
        "KFTypePositionY": [(0, 0.0), (dur_s, 0.0)],
        "KFTypeScaleX": [(0, 1.0), (dur_s, 1.0)],
        "KFTypeRotation": [(0, 0.0), (dur_s, 0.0)],
    }
    if extra:
        base.update(extra)
    return [make_kf(prop, pairs) for prop, pairs in base.items()]


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_fx5_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print(f"1. Copy seed...")
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

    print(f"3. Copy video...")
    local_path = project_dir / "assets" / "video" / video.name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, local_path)

    SEG_S = dur_sec / 8
    SEG_US = int(SEG_S * 1_000_000)

    # --- Segment definitions ---
    effects = [
        ("Original",         {}),
        ("Spin 360",         {"KFTypeRotation": [(0, 0.0), (SEG_S, 360.0)]}),
        ("Fade Out",         {"KFTypeAlpha": [(0, 1.0), (SEG_S, 0.0)]}),
        ("Saturation",       {"KFTypeSaturation": [(0, 0), (SEG_S, 100)]}),
        ("Contrast",         {"KFTypeContrast": [(0, 0), (SEG_S, 100)]}),
        ("Brightness",       {"KFTypeBrightness": [(0, 0), (SEG_S, 100)]}),
        ("Speed 2x",         {}),
        ("Slow 0.5x",        {}),
    ]

    HELPER_TEMPLATES = {
        "speeds": {"type": "speed", "speed": 1.0, "mode": 0, "curve_speed": None},
        "placeholder_infos": {"type": "placeholder_info", "meta_type": "none", "res_path": "", "res_text": "", "error_path": "", "error_text": ""},
        "canvases": {"type": "canvas_color", "color": "", "blur": 0, "image": "", "album_image": "", "image_id": "", "image_name": "", "source_platform": 0, "team_id": ""},
        "sound_channel_mappings": {"type": "none", "audio_channel_mapping": 0, "is_config_open": False},
        "material_colors": {"type": "material_color", "is_color_clip": False, "is_gradient": False, "solid_color": "", "gradient_colors": [], "gradient_percents": [], "gradient_angle": 90, "width": 0, "height": 0},
        "vocal_separations": {"type": "vocal_separation", "choice": 0, "removed_sounds": [], "time_range": None, "production_path": "", "final_algorithm": "", "enter_from": ""},
    }

    segs = []
    text_mats = []
    text_segs = []
    all_helpers = {k: [] for k in HELPER_TEMPLATES}
    text_track_id = uid()

    for i, (label, anim) in enumerate(effects):
        mat_id = uid()
        seg_id = uid()
        start = i * SEG_US
        src = min(i * SEG_US, dur_us - SEG_US)

        # Clone helper materials for this segment
        refs = []
        for key, tmpl in HELPER_TEMPLATES.items():
            hid = uid()
            mat = dict(tmpl)
            mat["id"] = hid
            all_helpers[key].append(mat)
            refs.append(hid)

        segs.append({
            "id": seg_id,
            "material_id": mat_id,
            "raw_segment_id": uid(),
            "target_timerange": {"start": start, "duration": SEG_US},
            "source_timerange": {"start": src, "duration": SEG_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1.0, "rotation": 0.0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": refs, "common_keyframes": lock_kfs(SEG_S, anim or None), "keyframe_refs": [],
        })

        if label == "Speed 2x":
            segs[-1]["speed"] = 2.0
            all_helpers["speeds"][-1]["speed"] = 2.0
        elif label == "Slow 0.5x":
            segs[-1]["speed"] = 0.5
            all_helpers["speeds"][-1]["speed"] = 0.5

        tmid = uid()
        text_mats.append({
            "id": tmid, "type": "text",
            "content": json.dumps({
                "styles": [{"range": [0, len(label.encode("utf-16-le"))], "size": 16,
                            "bold": True, "fill": {"alpha": 1, "content": {"render_type": "solid",
                                    "solid": {"alpha": 1, "color": [1, 0.42, 0]}}}}],
                "text": label,
            }),
            "duration": SEG_US, "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 16, "text_color": "#FF6B00",
        })
        text_segs.append({
            "id": uid(), "material_id": tmid, "raw_segment_id": text_track_id,
            "target_timerange": {"start": start, "duration": SEG_US},
            "source_timerange": {"start": start, "duration": SEG_US}, "speed": 1, "volume": 1,
            "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": -0.2}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [], "common_keyframes": [], "keyframe_refs": [],
        })

    # Build JSON
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = len(segs) * SEG_US
    dc["tracks"] = [
        {"id": uid(), "type": "video", "name": "video", "attribute": 0,
         "segments": segs, "is_default_name": False, "flag": 0},
        {"id": text_track_id, "type": "text", "name": "labels", "attribute": 0,
         "segments": text_segs, "is_default_name": False, "flag": 0},
    ]

    vids = []
    for i in range(len(segs)):
        vids.append(make_video_mat(uid(), local_path, dur_us))
    dc["materials"]["videos"] = vids
    dc["materials"]["texts"] = text_mats
    for key, items in all_helpers.items():
        dc["materials"][key] = items

    (project_dir / "draft_content.json").write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

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
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {len(segs)}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_fx5.py <video.mp4>")
        sys.exit(1)
    main()
