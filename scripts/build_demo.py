"""
Demo: all editing techniques on one video, 3s per segment.
Uses seed 0517 with UUID replacement.
"""

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


def make_companions(for_video: bool = True):
    ids, materials = [], []
    def add(tp, data):
        data["id"] = uid()
        ids.append(data["id"])
        materials.append({"type": tp, "data": data})
    add("speeds", {"type": "speed", "speed": 1, "mode": 0, "curve_speed": None})
    add("placeholder_infos", {"type": "placeholder_info", "error_path": "", "error_text": "", "meta_type": "none", "res_path": "", "res_text": ""})
    add("sound_channel_mappings", {"type": "none", "audio_channel_mapping": 0, "is_config_open": False})
    add("vocal_separations", {"type": "vocal_separation", "choice": 0, "enter_from": "", "final_algorithm": "", "production_path": "", "removed_sounds": [], "time_range": None})
    if for_video:
        add("canvases", {"type": "canvas_color", "album_image": "", "blur": 0, "color": "", "image": "", "image_id": "", "image_name": "", "source_platform": 0, "team_id": ""})
        add("material_colors", {"type": "material_color", "gradient_angle": 90, "gradient_colors": [], "gradient_percents": [], "height": 0, "is_color_clip": False, "is_gradient": False, "solid_color": "", "width": 0})
    return ids, materials


def main():
    video_path = sys.argv[1]
    script = sys.argv[2] if len(sys.argv) > 2 else ""
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_demo_{uuid.uuid4().hex[:6]}"
    project_dir = DRAFTS_DIR / name
    new_id = uid()

    print("Copying seed...")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = json.loads((project_dir / "draft_content.json").read_text("utf-8")).get("id")
    print(f"Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_uuid(project_dir, old_id, new_id)

    # copy video into assets
    assets_dir = project_dir / "assets" / "video"
    assets_dir.mkdir(parents=True, exist_ok=True)
    local_path = assets_dir / video.name
    shutil.copy2(video, local_path)

    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    SEG_DUR = 3_000_000  # 3 seconds per segment
    n_segs = max(1, min(9, int(dur_sec * 1_000_000 / SEG_DUR)))
    print(f"Video: {dur_sec:.1f}s, segments: {n_segs} ({(n_segs*3)}s total)")

    # --- create video materials (one per segment, all ref same file) ---
    video_materials = []
    for i in range(n_segs):
        mat_id = uid()
        mat = {
            "id": mat_id, "path": str(local_path), "material_name": video.name,
            "type": "video", "duration": SEG_DUR * 3,
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

    # --- segments with different effects ---
    segments = []
    extra_refs = []  # extra_material_refs for entire track (companions shared)

    for i in range(n_segs):
        seg_id = uid()
        mat_id = video_materials[i]["id"]
        track_id = uid()
        cids, cmats = make_companions(for_video=True)
        extra_refs = cids

        start = i * SEG_DUR
        seg_dur = SEG_DUR

        src_start = min(i * SEG_DUR, int(dur_sec * 1_000_000) - SEG_DUR)
        seg = {
            "id": seg_id,
            "material_id": mat_id,
            "raw_segment_id": track_id,
            "target_timerange": {"start": start, "duration": seg_dur},
            "source_timerange": {"start": src_start, "duration": seg_dur},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": cids,
            "common_keyframes": [],
            "keyframe_refs": [],
        }

        # Apply different technique per segment
        if i == 0:
            pass  # original
        elif i == 1:
            seg["speed"] = 2.0
        elif i == 2:
            seg["common_keyframes"] = [
                {"id": uid_hex(), "keyframe_list": [
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": 0, "values": [1]},
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": seg_dur, "values": [1.5]},
                ], "material_id": "", "property_type": "UNIFORM_SCALE"},
            ]
        elif i == 3:
            seg["common_keyframes"] = [
                {"id": uid_hex(), "keyframe_list": [
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": 0, "values": [0]},
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": seg_dur, "values": [45]},
                ], "material_id": "", "property_type": "KFTypeRotation"},
            ]
        elif i == 4:
            seg["clip"]["alpha"] = 0.6
            seg["common_keyframes"] = [
                {"id": uid_hex(), "keyframe_list": [
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": 0, "values": [0]},
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": seg_dur, "values": [0.5]},
                ], "material_id": "", "property_type": "KFTypeSaturation"},
            ]
        elif i == 5:
            seg["clip"]["transform"]["x"] = -0.3
            seg["common_keyframes"] = [
                {"id": uid_hex(), "keyframe_list": [
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": 0, "values": [0]},
                    {"curveType": "Line", "graphID": "", "left_control": {"x": 0, "y": 0}, "right_control": {"x": 0, "y": 0}, "id": uid_hex(), "time_offset": seg_dur, "values": [0.5]},
                ], "material_id": "", "property_type": "KFTypePositionY"},
            ]
        elif i == 6:
            seg["speed"] = 0.5
        elif i == 7:
            seg["clip"]["rotation"] = 15
            seg["clip"]["scale"]["x"] = 1.3
            seg["clip"]["scale"]["y"] = 1.3

        segments.append((seg, cmats))

    # build video track
    track = {
        "id": uid(),
        "type": "video",
        "name": "video",
        "attribute": 0,
        "segments": [s[0] for s in segments],
        "is_default_name": False,
        "flag": 0,
    }

    # build text segments
    text_track = {
        "id": uid(),
        "type": "text",
        "name": "labels",
        "attribute": 0,
        "segments": [],
        "is_default_name": False,
        "flag": 0,
    }

    labels = [
        "Оригинал", "Speed 2x", "Keyframe Zoom", "Rotation 45°",
        "Opacity+Saturation", "Pan Down", "Slow Motion 0.5x", "Scale+Rotate",
    ]
    text_mat_id = uid()
    text_materials = []

    for i, (seg, _) in enumerate(segments):
        start = i * SEG_DUR
        label = labels[i] if i < len(labels) else f"Effect {i+1}"
        tmat_id = uid()
        text_material = {
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
            "duration": SEG_DUR,
            "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 18, "text_color": "#FF6B00",
        }
        text_materials.append(text_material)

        tseg = {
            "id": uid(),
            "material_id": tmat_id,
            "raw_segment_id": text_track["id"],
            "target_timerange": {"start": start, "duration": SEG_DUR},
            "source_timerange": {"start": start, "duration": SEG_DUR},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": -0.2}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [],
            "common_keyframes": [], "keyframe_refs": [],
        }
        text_track["segments"].append(tseg)

    # build draft_content.json
    content_path = project_dir / "draft_content.json"
    dc = json.loads(content_path.read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = len(segments) * SEG_DUR
    dc["tracks"] = [track, text_track]
    dc["materials"]["videos"] = video_materials
    dc["materials"]["texts"] = text_materials

    for cm in [c for _, cs in segments for c in cs]:
        tp = cm["type"]
        if tp not in dc["materials"]:
            dc["materials"][tp] = []
        dc["materials"][tp].append(cm["data"])

    content_path.write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    # ALSO update Timeline subdir draft_content.json — CapCut reads timeline from there
    tl_dir = project_dir / "Timelines" / new_id
    tl_content = tl_dir / "draft_content.json"
    if tl_content.exists():
        # Copy tracks, segments, materials from root
        tl_dc = json.loads(tl_content.read_text("utf-8"))
        tl_dc["tracks"] = dc["tracks"]
        tl_dc["materials"] = dc["materials"]
        tl_dc["duration"] = dc["duration"]
        tl_dc["name"] = dc["name"]
        tl_content.write_text(json.dumps(tl_dc, ensure_ascii=False), encoding="utf-8")

    # update meta
    meta_path = project_dir / "draft_meta_info.json"
    if meta_path.exists():
        m = json.loads(meta_path.read_text("utf-8"))
        m["draft_id"] = new_id
        m["draft_name"] = name
        m["draft_fold_path"] = str(project_dir).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
        m["tm_duration"] = len(segments) * SEG_DUR
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {len(segments)}, total: {len(segments)*3}s")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_demo.py <video.mp4>")
        sys.exit(1)
    main()
