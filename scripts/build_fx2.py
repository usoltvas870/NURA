"""CapCut demo — Spin, Fade, Speed, Saturation, Contrast, Brightness — через seed + capcut-cli."""

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


def make_kf(prop: str, pairs: list) -> dict:
    return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_fx2_{uuid.uuid4().hex[:6]}"
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

    # Read seed materials as base (keep helper materials)
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
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
    video_mat["width"] = 1920
    video_mat["height"] = 1080

    SEG = int(dur_sec / 8 * 1_000_000)
    SEG_S = SEG / 1_000_000

    effects = [
        ("Original",       None),
        ("Spin 360",       lambda s: [make_kf("KFTypeRotation", [(0, 0), (s, 360)])]),
        ("Fade Out",       lambda s: [make_kf("alpha", [(0, 1.0), (s, 0)])]),
        ("Saturation",     lambda s: [make_kf("saturation", [(0, 0), (s, 1)])]),
        ("Contrast",       lambda s: [make_kf("contrast", [(0, 0), (s, 1)])]),
        ("Brightness",     lambda s: [make_kf("brightness", [(0, 0), (s, 1)])]),
        ("Speed 2x",       None),
        ("Slow 0.5x",      None),
    ]

    video_segments = []
    text_materials = []
    text_segments = []
    text_track_id = uid()

    # Clone helper materials from seed for each segment
    seed_helpers = {}
    for k, v in dc.get("materials", {}).items():
        if isinstance(v, list) and k not in ("videos", "texts", "images", "audios"):
            seed_helpers[k] = [dict(item) for item in v]

    for i, (label, kf_fn) in enumerate(effects):
        start_us = i * SEG
        src_start = min(i * SEG, dur_us - SEG)
        seg_id = uid()

        # Clone helper references from seed's first segment
        extra_refs = []
        for k, items in seed_helpers.items():
            if items:
                new_items = []
                for item in items:
                    new_id = uid()
                    item["id"] = new_id
                    new_items.append(item)
                seed_helpers[k] = new_items
                extra_refs.append(new_items[0]["id"])

        kfs = kf_fn(SEG_S) if kf_fn else []

        video_segments.append({
            "id": seg_id, "material_id": video_mat["id"], "raw_segment_id": uid(),
            "target_timerange": {"start": start_us, "duration": SEG},
            "source_timerange": {"start": src_start, "duration": SEG},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {"alpha": 1.0, "rotation": 0.0, "scale": {"x": 1, "y": 1},
                     "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}},
            "render_index": 14000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": extra_refs,
            "common_keyframes": kfs, "keyframe_refs": [],
        })

        tmid = uid()
        text_materials.append({
            "id": tmid, "type": "text",
            "content": json.dumps({
                "styles": [{"range": [0, len(label.encode("utf-16-le"))], "size": 16,
                            "bold": True, "fill": {"alpha": 1, "content": {"render_type": "solid",
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

    dc["id"] = new_id
    dc["name"] = name
    dc["duration"] = len(video_segments) * SEG
    dc["tracks"] = [
        {"id": uid(), "type": "video", "name": "video", "attribute": 0,
         "segments": video_segments, "is_default_name": False, "flag": 0},
        {"id": text_track_id, "type": "text", "name": "labels", "attribute": 0,
         "segments": text_segments, "is_default_name": False, "flag": 0},
    ]
    dc["materials"]["videos"] = [video_mat]
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

    # --- Speed via capcut-cli ---
    print("4. Setting speed via capcut-cli...")
    for i in [6, 7]:
        seg_id = video_segments[i]["id"]
        val = "2.0" if i == 6 else "0.5"
        subprocess.run(
            ["npx.cmd", "capcut-cli", "speed", str(project_dir), seg_id, val],
            capture_output=True, text=True, cwd=NURA_ROOT, shell=True,
        )
        print(f"   {effects[i][0]}: speed {val}x")

    # Sync timeline
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
        print("Usage: python scripts/build_fx2.py <video.mp4>")
        sys.exit(1)
    main()
