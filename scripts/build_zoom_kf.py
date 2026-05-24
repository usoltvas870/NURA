"""CapCut keyframe zoom demo — прямой JSON, формат из apply-zoom.py."""

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


def copy_seed(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))


def replace_all_uuids(project_dir: Path, old_id: str, new_id: str) -> None:
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


def make_zoom_keyframes(slot_us: int, scale_start: float, scale_end: float) -> list:
    return [
        {"property_type": "KFTypePositionX", "keyframe_list": [
            {"time_offset": 0, "values": [0.0]},
            {"time_offset": slot_us, "values": [0.0]},
        ]},
        {"property_type": "KFTypePositionY", "keyframe_list": [
            {"time_offset": 0, "values": [0.0]},
            {"time_offset": slot_us, "values": [0.0]},
        ]},
        {"property_type": "KFTypeScaleX", "keyframe_list": [
            {"time_offset": 0, "values": [scale_start]},
            {"time_offset": slot_us, "values": [scale_end]},
        ]},
        {"property_type": "KFTypeRotation", "keyframe_list": [
            {"time_offset": 0, "values": [0.0]},
            {"time_offset": slot_us, "values": [0.0]},
        ]},
    ]


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_zoom_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print("1. Copy seed 0517...")
    copy_seed(SEED, project_dir)

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"2. Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_all_uuids(project_dir, old_id, new_id)

    print("3. Copy video...")
    local_path = project_dir / "assets" / "video" / video.name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, local_path)

    # Segments: each 3s with its own zoom animation
    SEG_DUR_S = 3.0
    SEG_DUR_US = int(SEG_DUR_S * 1_000_000)
    n_segs = max(1, min(8, int(dur_sec / SEG_DUR_S)))

    zoom_configs = [
        ("Original", 1.0, 1.0),
        ("Zoom In 1.3x", 1.0, 1.3),
        ("Zoom In 1.5x", 1.0, 1.5),
        ("Zoom In 1.8x", 1.0, 1.8),
        ("Zoom In 2.0x", 1.0, 2.0),
        ("Zoom In 2.5x", 1.0, 2.5),
        ("Zoom In 3.0x", 1.0, 3.0),
        ("Back to 1x", 1.0, 1.0),
    ]

    video_materials = []
    video_segments = []
    label_segments = []

    for i in range(min(n_segs, len(zoom_configs))):
        label, s_start, s_end = zoom_configs[i]
        mat_id = uid()
        seg_id = uid()
        seg_raw_id = uid()
        start_us = i * SEG_DUR_US
        src_start = min(i * SEG_DUR_US, dur_us - SEG_DUR_US)

        # Video material
        video_materials.append({
            "id": mat_id, "unique_id": "", "type": "video",
            "duration": dur_us,
            "path": str(local_path), "media_path": "", "local_id": "",
            "has_audio": True, "reverse_path": "", "intensifies_path": "",
            "reverse_intensifies_path": "", "intensifies_audio_path": "",
            "cartoon_path": "", "width": 1920, "height": 1080,
            "category_id": "", "category_name": "local", "material_id": "",
            "material_name": local_path.name, "material_url": "",
            "crop": {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                     "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1},
            "crop_ratio": "free", "audio_fade": None, "crop_scale": 1.0,
            "extra_type_option": 0,
            "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
            "matting": {"flag": 0, "path": "", "interactiveTime": [], "has_use_quick_brush": False,
                        "strokes": [], "has_use_quick_eraser": False, "expansion": 0, "feather": 0,
                        "reverse": False, "custom_matting_id": "", "enable_matting_stroke": False},
            "source": 0, "source_platform": 0, "formula_id": "", "check_flag": 7,
            "video_algorithm": {"algorithms": [], "time_range": None, "path": "",
                                "gameplay_configs": [], "ai_in_painting_config": [],
                                "complement_frame_config": None, "motion_blur_config": None,
                                "deflicker": None, "noise_reduction": None, "quality_enhance": None,
                                "super_resolution": None, "ai_background_configs": [],
                                "smart_complement_frame": None, "aigc_generate": None,
                                "aigc_generate_list": [], "mouth_shape_driver": None,
                                "ai_expression_driven": None, "ai_motion_driven": None,
                                "image_interpretation": None,
                                "story_video_modify_video_config": {
                                    "task_id": "", "is_overwrite_last_video": False, "tracker_task_id": ""},
                                "skip_algorithm_index": []},
            "is_unified_beauty_mode": False, "object_locked": None, "smart_motion": None,
            "multi_camera_info": None, "freeze": None, "picture_from": "none",
            "picture_set_category_id": "", "picture_set_category_name": "",
            "team_id": "", "local_material_id": "", "origin_material_id": "",
            "request_id": "", "has_sound_separated": False,
            "is_text_edit_overdub": False, "is_ai_generate_content": False,
            "aigc_type": "none", "is_copyright": False, "aigc_history_id": "",
            "aigc_item_id": "", "local_material_from": "", "smart_match_info": None,
            "beauty_face_preset_infos": [], "beauty_body_preset_id": "",
            "beauty_face_auto_preset": {"preset_id": "", "name": "", "rate_map": "", "scene": ""},
            "beauty_face_auto_preset_infos": [], "beauty_body_auto_preset": None,
            "live_photo_timestamp": -1, "live_photo_cover_path": "",
            "content_feature_info": None, "corner_pin": None, "surface_trackings": [],
            "video_mask_stroke": {"resource_id": "", "path": "", "type": "", "color": "",
                                  "size": 0, "alpha": 0, "distance": 0, "texture": 0,
                                  "horizontal_shift": 0, "vertical_shift": 0},
            "video_mask_shadow": {"resource_id": "", "path": "", "color": "", "alpha": 0,
                                  "blur": 0, "distance": 0, "angle": 0},
        })

        # Video segment
        seg = {
            "id": seg_id,
            "material_id": mat_id,
            "raw_segment_id": seg_raw_id,
            "target_timerange": {"start": start_us, "duration": SEG_DUR_US},
            "source_timerange": {"start": src_start, "duration": SEG_DUR_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {
                "alpha": 1.0,
                "flip": {"horizontal": False, "vertical": False},
                "rotation": 0.0,
                "scale": {"x": s_start, "y": s_start},
                "transform": {"x": 0.0, "y": 0.0},
            },
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [],
            "common_keyframes": make_zoom_keyframes(SEG_DUR_US, s_start, s_end),
            "keyframe_refs": [],
        }
        video_segments.append(seg)

        # Text label
        tmat_id = uid()
        label_segments.append({
            "text_material": {
                "id": tmat_id, "type": "text",
                "content": json.dumps({
                    "styles": [{
                        "range": [0, len(label.encode("utf-16-le"))],
                        "size": 16, "bold": True, "italic": False, "underline": False,
                        "fill": {"alpha": 1, "content": {"render_type": "solid", "solid": {"alpha": 1, "color": [1, 0.42, 0]}}},
                    }],
                    "text": label,
                }),
                "duration": SEG_DUR_US, "width": 1920, "height": 1080,
                "alignment": 1, "font_size": 16, "text_color": "#FF6B00",
            },
            "segment": {
                "id": uid(), "material_id": tmat_id,
                "raw_segment_id": uid(),
                "target_timerange": {"start": start_us, "duration": SEG_DUR_US},
                "source_timerange": {"start": start_us, "duration": SEG_DUR_US},
                "speed": 1, "volume": 1, "visible": True, "reverse": False,
                "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": -0.2}, "flip": {"horizontal": False, "vertical": False}},
                "render_index": 12000 + i, "track_render_index": 0, "track_attribute": 0,
                "extra_material_refs": [], "common_keyframes": [], "keyframe_refs": [],
            },
        })

    # Build draft_content.json
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = n_segs * SEG_DUR_US

    video_track = {
        "id": uid(), "type": "video", "name": "video",
        "attribute": 0, "segments": video_segments,
        "is_default_name": False, "flag": 0,
    }
    text_track = {
        "id": uid(), "type": "text", "name": "labels",
        "attribute": 0,
        "segments": [ls["segment"] for ls in label_segments],
        "is_default_name": False, "flag": 0,
    }
    dc["tracks"] = [video_track, text_track]

    # Materials — keep seed helpers, replace videos/texts
    dc["materials"]["videos"] = video_materials
    dc["materials"]["texts"] = [ls["text_material"] for ls in label_segments]

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
        m["tm_duration"] = n_segs * SEG_DUR_US
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {n_segs}, total: {n_segs * SEG_DUR_S:.0f}s")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_zoom_kf.py <video.mp4>")
        sys.exit(1)
    main()
