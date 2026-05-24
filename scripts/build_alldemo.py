"""CapCut — демо всех инструментов на одном ролике."""

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
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, shell=True)
        m = __import__("re").search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            return h * 3600 + mi * 60 + s + ms / 100
    except Exception:
        pass
    return 0.0


def capcut(*args: str, input_text: str | None = None) -> None:
    cmd = ["npx.cmd", "capcut-cli", *args]
    r = subprocess.run(cmd, input=input_text, capture_output=True, text=True, cwd=NURA_ROOT, shell=True)
    if r.returncode != 0:
        print(f"  capcut error: {r.stderr.strip()}")


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_alldemo_{uuid.uuid4().hex[:6]}"
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

    SEG_DUR_S = 2.5
    SEG_DUR_US = int(SEG_DUR_S * 1_000_000)
    n_segs = max(1, min(14, int(dur_sec / SEG_DUR_S)))

    # --- Segment definitions ---
    # (label, clip_scale, keyframes_maker, extra_capcut_commands)
    segments_def = []

    def make_kf(prop, pairs):
        return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}

    for i in range(min(n_segs, 14)):
        start_s = i * SEG_DUR_S
        end_s = min((i + 1) * SEG_DUR_S, dur_sec)

        clip = {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}}
        kfs = []
        extra = []
        label = f"Seg {i+1}"

        if i == 0:
            label = "1. Zoom In"
            clip["scale"] = {"x": 1.0, "y": 1.0}
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1.0), (SEG_DUR_S, 1.5)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
        elif i == 1:
            label = "2. Zoom Out"
            clip["scale"] = {"x": 1.5, "y": 1.5}
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1.5), (SEG_DUR_S, 1.0)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
        elif i == 2:
            label = "3. Slide Right"
            clip["transform"] = {"x": -0.5, "y": 0}
            kfs = [
                make_kf("KFTypePositionX", [(0, -0.5), (SEG_DUR_S, 0.5)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
        elif i == 3:
            label = "4. Spin"
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 360)]),
            ]
        elif i == 4:
            label = "5. Fade Out"
            clip["alpha"] = 1.0
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
            kfs.append(make_kf("alpha", [(0, 1.0), (SEG_DUR_S, 0)]))
        elif i == 5:
            label = "6. Speed 2x"
            extra.append(("speed", ()))
        elif i == 6:
            label = "7. Slow 0.5x"
            extra.append(("speed", ()))
        elif i == 7:
            label = "8. Saturation"
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
            kfs.append(make_kf("saturation", [(0, 0), (SEG_DUR_S, 100)]))
        elif i == 8:
            label = "9. Contrast"
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
            kfs.append(make_kf("contrast", [(0, 0), (SEG_DUR_S, 100)]))
        elif i == 9:
            label = "10. Brightness"
            kfs = [
                make_kf("KFTypePositionX", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypePositionY", [(0, 0), (SEG_DUR_S, 0)]),
                make_kf("KFTypeScaleX", [(0, 1), (SEG_DUR_S, 1)]),
                make_kf("KFTypeRotation", [(0, 0), (SEG_DUR_S, 0)]),
            ]
            kfs.append(make_kf("brightness", [(0, 0), (SEG_DUR_S, 100)]))
        elif i == 10:
            label = "11. Transition"
            extra.append(("transition",))
        elif i == 11:
            label = "12. Effect VHS"
            extra.append(("effect",))
        elif i == 12:
            label = "13. Mask Heart"
            extra.append(("mask",))
        elif i == 13:
            label = "14. Bg Blur"
            extra.append(("bgblur",))

        segments_def.append((label, clip, kfs, extra, start_s, end_s))

    # --- Build JSON ---
    video_materials = []
    video_segments = []
    text_materials = []
    text_segments = []
    # map seg_id -> (label, extra_cmds) for post-processing
    post_ops = {}
    raw_track_id = uid()
    text_track_id = uid()

    for i, (label, clip, kfs, extra, start_s, end_s) in enumerate(segments_def):
        mat_id = uid()
        seg_id = uid()
        seg_raw_id = uid()
        start_us = i * SEG_DUR_US
        src_start = min(i * SEG_DUR_US, dur_us - SEG_DUR_US)

        video_materials.append({
            "id": mat_id, "type": "video", "duration": dur_us,
            "path": str(local_path), "material_name": local_path.name,
            "width": 1920, "height": 1080, "has_audio": True, "check_flag": 7,
            "crop": {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                     "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1},
            "crop_ratio": "free", "crop_scale": 1, "extra_type_option": 0,
            "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
            "matting": {"flag": 0, "path": "", "interactiveTime": [], "strokes": [],
                        "has_use_quick_brush": False, "has_use_quick_eraser": False,
                        "expansion": 0, "feather": 0, "reverse": False,
                        "custom_matting_id": "", "enable_matting_stroke": False},
            "source": 0, "source_platform": 0, "formula_id": "",
            "video_algorithm": {"algorithms": []},
            "is_unified_beauty_mode": False, "object_locked": None, "smart_motion": None,
            "freeze": None, "picture_from": "none",
            "is_ai_generate_content": False, "aigc_type": "none", "is_copyright": False,
        })

        seg = {
            "id": seg_id, "material_id": mat_id, "raw_segment_id": seg_raw_id,
            "target_timerange": {"start": start_us, "duration": SEG_DUR_US},
            "source_timerange": {"start": src_start, "duration": SEG_DUR_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": clip,
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [], "common_keyframes": kfs, "keyframe_refs": [],
        }

        # Speed override
        if extra and extra[0][0] == "speed":
            if i == 5:
                seg["speed"] = 2.0
            elif i == 6:
                seg["speed"] = 0.5

        video_segments.append(seg)
        post_ops[seg_id] = (label, extra, start_s, end_s - start_s)

        # Text label
        dur_label = end_s - start_s
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
            "duration": SEG_DUR_US, "width": 1920, "height": 1080,
            "alignment": 1, "font_size": 16, "text_color": "#FF6B00",
        })
        text_segments.append({
            "id": uid(), "material_id": tmid, "raw_segment_id": text_track_id,
            "target_timerange": {"start": start_us, "duration": SEG_DUR_US},
            "source_timerange": {"start": start_us, "duration": SEG_DUR_US},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": -0.2},
                     "flip": {"horizontal": False, "vertical": False}},
            "render_index": 12000, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [], "common_keyframes": [], "keyframe_refs": [],
        })

    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = len(video_segments) * SEG_DUR_US
    dc["tracks"] = [
        {"id": uid(), "type": "video", "name": "video", "attribute": 0,
         "segments": video_segments, "is_default_name": False, "flag": 0},
        {"id": text_track_id, "type": "text", "name": "labels", "attribute": 0,
         "segments": text_segments, "is_default_name": False, "flag": 0},
    ]
    dc["materials"]["videos"] = video_materials
    dc["materials"]["texts"] = text_materials

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

    # --- Post-processing via capcut-cli ---
    print("4. Applying effects via capcut-cli...")
    seg_ids_list = list(post_ops.keys())

    for idx, (seg_id, (label, extra, start_s, dur_s)) in enumerate(post_ops.items()):
        if not extra:
            continue
        cmd_type = extra[0][0]

        if cmd_type == "effect":
            print(f"   {label}: effect shake")
            capcut("add-effect", str(project_dir), "shake", f"{start_s}s", f"{dur_s}s")
        elif cmd_type == "mask":
            print(f"   {label}: mask heart")
            capcut("mask", str(project_dir), seg_id, "heart", "--size", "0.5")
        elif cmd_type == "bgblur":
            print(f"   {label}: bg-blur 2")
            capcut("bg-blur", str(project_dir), seg_id, "2")

    # Transition between seg 10 and 11
    if len(seg_ids_list) > 10:
        print("   Transition dissolve on seg 11")
        capcut("transition", str(project_dir), seg_ids_list[10], "dissolve", "--duration", "0.5s")

    # Text animation on first 4 text labels
    text_seg_ids = []
    info_out = subprocess.run(
        ["npx.cmd", "capcut-cli", "segments", str(project_dir), "--track", "text"],
        capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
    )
    try:
        all_segs = json.loads(info_out.stdout)
        text_seg_ids = [s.get("id", "") for s in (all_segs if isinstance(all_segs, list) else [])]
    except Exception:
        pass

    for i, tsid in enumerate(text_seg_ids[:4]):
        if i == 0:
            capcut("text-anim", str(project_dir), tsid, "--intro", "typewriter")
        elif i == 1:
            capcut("text-anim", str(project_dir), tsid, "--intro", "fade-in")
        elif i == 2:
            capcut("text-anim", str(project_dir), tsid, "--intro", "zoom-in-text")
        elif i == 3:
            capcut("text-anim", str(project_dir), tsid, "--outro", "fade-out")

    # Sync timeline after all capcut changes
    if tl_content.exists():
        dc_upd = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc_upd["tracks"]
        tldc["materials"] = dc_upd["materials"]
        tldc["duration"] = dc_upd["duration"]
        tldc["name"] = dc_upd["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")
    print(f"Segments: {len(video_segments)}, total: {len(video_segments) * SEG_DUR_S:.0f}s")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_alldemo.py <video.mp4>")
        sys.exit(1)
    main()
