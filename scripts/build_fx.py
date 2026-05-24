"""CapCut — demo всех инструментов (чиним speed, saturation, contrast, alpha, rotation)."""

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


def uid_hex() -> str:
    return uuid.uuid4().hex


def probe_duration(path: Path) -> float:
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, shell=True)
        m = __import__("re").search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            return h * 3600 + mi * 60 + s + ms / 100
    except Exception:
        pass
    return 0.0


def make_video_mat(uid_str: str, path: Path, dur_us: int) -> dict:
    return {
        "id": uid_str, "unique_id": "", "type": "video", "duration": dur_us,
        "path": str(path), "media_path": "", "local_id": "",
        "has_audio": True, "reverse_path": "", "intensifies_path": "",
        "cartoon_path": "", "width": 1920, "height": 1080,
        "category_id": "", "category_name": "local", "material_id": "",
        "material_name": path.name, "material_url": "",
        "crop": {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                 "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1},
        "crop_ratio": "free", "audio_fade": None, "crop_scale": 1, "extra_type_option": 0,
        "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
        "matting": {"flag": 0, "path": "", "interactiveTime": [], "has_use_quick_brush": False,
                    "strokes": [], "has_use_quick_eraser": False, "expansion": 0, "feather": 0,
                    "reverse": False, "custom_matting_id": "", "enable_matting_stroke": False},
        "source": 0, "source_platform": 0, "formula_id": "", "check_flag": 7,
        "video_algorithm": {"algorithms": [], "time_range": None, "path": "", "gameplay_configs": [],
                            "motion_blur_config": None, "deflicker": None, "noise_reduction": None,
                            "quality_enhance": None, "super_resolution": None},
        "is_unified_beauty_mode": False, "object_locked": None, "freeze": None,
        "is_ai_generate_content": False, "is_copyright": False,
    }


def make_kf(prop: str, pairs: list) -> dict:
    return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}


def make_helper(refs: dict, tp: str, data: dict) -> str:
    """Add a helper material, return its ID."""
    hid = uid()
    data["id"] = hid
    refs.setdefault(tp, []).append(data)
    return hid


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_fx_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print(f"1. Copy seed 0517...")
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

    # --- Segment definitions ---
    SEG = int(dur_sec / 8 * 1_000_000)  # 8 segments
    SEG_S = SEG / 1_000_000

    effects = [
        # (label, clip_override, kfs_maker, speed_val, helper_mats)
        ("Original", {}, None, 1.0, []),
        ("Spin 360", {}, lambda s: [make_kf("KFTypeRotation", [(0, 0), (s, 360)])], 1.0, []),
        ("Fade Out", {}, lambda s: [make_kf("KFTypeAlpha", [(0, 1.0), (s, 0)])], 1.0, []),
        ("Speed 2x", {}, None, 2.0, [("speeds", {"type": "speed", "speed": 2.0, "mode": 0, "curve_speed": None})]),
        ("Saturation", {}, lambda s: [make_kf("KFTypeSaturation", [(0, 0), (s, 100)])], 1.0, []),
        ("Contrast", {}, lambda s: [make_kf("KFTypeContrast", [(0, 0), (s, 100)])], 1.0, []),
        ("Brightness", {}, lambda s: [make_kf("KFTypeBrightness", [(0, 0), (s, 100)])], 1.0, []),
        ("Slow 0.5x", {}, None, 0.5, [("speeds", {"type": "speed", "speed": 0.5, "mode": 0, "curve_speed": None})]),
    ]

    # Build
    video_materials = []
    video_segments = []
    text_materials = []
    text_segments = []
    text_track_id = uid()
    helper_mats_all = {}  # type -> [materials]

    for i, (label, clip_ov, kf_fn, speed_val, helpers) in enumerate(effects):
        mat_id = uid()
        seg_id = uid()
        start_us = i * SEG
        src_start = min(i * SEG, dur_us - SEG)

        video_materials.append(make_video_mat(mat_id, local_path, dur_us))

        # Helper material refs
        extra_refs = []
        if speed_val != 1.0:
            for tp, data in helpers:
                hid = make_helper(helper_mats_all, tp, data)
                extra_refs.append(hid)
        # Also add standard helpers from seed
        # (speed, placeholder_info, canvas, sound_channel_mapping, material_color, vocal_separation)
        if speed_val == 1.0:
            hid = make_helper(helper_mats_all, "speeds", {"type": "speed", "speed": 1.0, "mode": 0, "curve_speed": None})
            extra_refs.append(hid)

        clip = {"alpha": 1.0, "rotation": 0.0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}}
        clip.update(clip_ov)

        kfs = []
        if kf_fn:
            kfs = kf_fn(SEG_S)

        video_segments.append({
            "id": seg_id, "material_id": mat_id, "raw_segment_id": uid(),
            "target_timerange": {"start": start_us, "duration": SEG},
            "source_timerange": {"start": src_start, "duration": SEG},
            "speed": speed_val, "volume": 1, "visible": True, "reverse": False,
            "clip": clip,
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": extra_refs,
            "common_keyframes": kfs, "keyframe_refs": [],
        })

        # Text label
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
            "duration": SEG, "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 16, "text_color": "#FF6B00",
        })
        text_segments.append({
            "id": uid(), "material_id": tmid, "raw_segment_id": text_track_id,
            "target_timerange": {"start": start_us, "duration": SEG},
            "source_timerange": {"start": start_us, "duration": SEG},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": -0.2},
                     "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [], "common_keyframes": [], "keyframe_refs": [],
        })

    # --- Build JSON ---
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = len(video_segments) * SEG

    # Merge helper materials from seed
    seed_helper_keys = ["speeds", "placeholder_infos", "canvases", "sound_channel_mappings",
                        "material_colors", "vocal_separations"]
    for key in seed_helper_keys:
        if key not in helper_mats_all:
            helper_mats_all[key] = dc["materials"].get(key, [])

    dc["materials"] = helper_mats_all
    dc["materials"]["videos"] = video_materials
    dc["materials"]["texts"] = text_materials

    dc["tracks"] = [
        {"id": uid(), "type": "video", "name": "video", "attribute": 0,
         "segments": video_segments, "is_default_name": False, "flag": 0},
        {"id": text_track_id, "type": "text", "name": "labels", "attribute": 0,
         "segments": text_segments, "is_default_name": False, "flag": 0},
    ]

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

    # --- Apply optional effects via capcut-cli ---
    print(f"4. Additional effects via capcut-cli...")
    for i in [3, 7]:  # Speed 2x, Slow 0.5x
        seg_id = video_segments[i]["id"]
        subprocess.run(
            ["npx.cmd", "capcut-cli", "speed", str(project_dir), seg_id, str(effects[i][3])],
            capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
        )
        print(f"   {effects[i][0]}: speed via capcut-cli")

    # Sync timeline after capcut changes
    if tl_content.exists():
        dc_upd = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc_upd["tracks"]
        tldc["materials"] = dc_upd["materials"]
        tldc["duration"] = dc_upd["duration"]
        tldc["name"] = dc_upd["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {len(video_segments)}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_fx.py <video.mp4>")
        sys.exit(1)
    main()
