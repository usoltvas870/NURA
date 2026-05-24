"""CapCut — все эффекты, гибрид: capcut-cli для init/video/speed + прямой JSON для keyframes."""

import json
import subprocess
import sys
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = NURA_ROOT / "videos" / "template"
DRAFTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
CAPCUT_EXE = Path.home() / "AppData/Local/CapCut/Apps/CapCut.exe"


def cmd(args: str) -> str:
    r = subprocess.run(f'cmd /c "{args} 2>&1"', capture_output=True, text=True, shell=True, cwd=NURA_ROOT)
    return r.stdout.strip()


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


def make_kf(prop: str, pairs: list) -> dict:
    return {"property_type": prop, "keyframe_list": [{"time_offset": int(t * 1_000_000), "values": [v]} for t, v in pairs]}


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_fx4_{uuid.uuid4().hex[:6]}"
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print(f"1. Init project via capcut-cli: {name}")
    cmd(f'npx.cmd capcut-cli init {name} --template {TEMPLATE} --drafts "{DRAFTS}"')
    project = DRAFTS / name
    if not project.exists():
        candidates = list(DRAFTS.glob(f"{name}*"))
        project = candidates[0] if candidates else project

    print(f"2. Add video")
    cmd(f'npx.cmd capcut-cli add-video "{project}" {video} 0 {dur_sec:.2f}s')

    # Get segment info
    seg_out = cmd(f'npx.cmd capcut-cli segments "{project}" --track video')
    seg_data = json.loads(seg_out)
    seg_id = seg_data[0]["id"]
    print(f"   seg_id={seg_id[:12]}...")

    # Read current state
    dc = json.loads((project / "draft_content.json").read_text("utf-8"))
    seg = None
    for t in dc.get("tracks", []):
        for s in t.get("segments", []):
            if s.get("id") == seg_id:
                seg = s
                break
    if not seg:
        print("ERROR: segment not found")
        sys.exit(1)

    # --- Build all keyframes directly in JSON ---
    SEG_S = dur_sec / 8

    effects = [
        ("Original", {}),
        ("Spin 360", {"KFTypeRotation": [(0, 0), (SEG_S, 360), (SEG_S + 1e-6, 0)]}),
        ("Fade Out", {"KFTypeAlpha": [(0, 1.0), (SEG_S, 0), (SEG_S + 1e-6, 1.0)]}),
        ("Saturation", {"KFTypeSaturation": [(0, 0), (SEG_S, 100), (SEG_S + 1e-6, 0)]}),
        ("Contrast", {"KFTypeContrast": [(0, 0), (SEG_S, 100), (SEG_S + 1e-6, 0)]}),
        ("Brightness", {"KFTypeBrightness": [(0, 0), (SEG_S, 100), (SEG_S + 1e-6, 0)]}),
        ("Speed 2x", {}),
        ("Slow 0.5x", {}),
    ]

    # All possible properties with their neutral lock values
    ALL_PROPS = {
        "KFTypeScaleX": 1.0,
        "KFTypePositionX": 0.0,
        "KFTypePositionY": 0.0,
        "KFTypeRotation": 0.0,
        "KFTypeAlpha": 1.0,
        "KFTypeSaturation": 0,
        "KFTypeContrast": 0,
        "KFTypeBrightness": 0,
    }

    all_kf_props = {}  # prop_name -> [(time_seconds, value), ...]

    for i, (label, anim) in enumerate(effects):
        t_start = i * SEG_S
        t_end = min((i + 1) * SEG_S, dur_sec)

        for prop in anim:
            pairs = anim[prop]
            all_kf_props.setdefault(prop, []).append((t_start + pairs[0][0], pairs[0][1]))
            all_kf_props.setdefault(prop, []).append((t_start + pairs[1][0], pairs[1][1]))

        # Speed via capcut-cli (post-processing)
        if label == "Speed 2x":
            cmd(f'npx.cmd capcut-cli speed "{project}" {seg_id} 2.0')
        elif label == "Slow 0.5x":
            cmd(f'npx.cmd capcut-cli speed "{project}" {seg_id} 0.5')

    # Sort each prop's keyframe list by time (for cleaner JSON/handling)
    for prop in all_kf_props:
        all_kf_props[prop].sort(key=lambda x: x[0])

    # Build common_keyframes
    seg["common_keyframes"] = [make_kf(prop, pairs) for prop, pairs in all_kf_props.items()]
    seg["keyframe_refs"] = []

    # --- Write back ---
    dc["name"] = name
    dc["duration"] = dur_us

    (project / "draft_content.json").write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    # Timeline subdir
    new_id = dc.get("id", "")
    tl_content = project / "Timelines" / new_id / "draft_content.json"
    if tl_content.exists():
        tldc = json.loads(tl_content.read_text("utf-8"))
        for t in dc.get("tracks", []):
            for i, ot in enumerate(tldc.get("tracks", [])):
                if ot.get("type") == t.get("type"):
                    tldc["tracks"][i] = t
        tldc["materials"] = dc["materials"]
        tldc["duration"] = dc["duration"]
        tldc["name"] = dc["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    # Meta
    meta_path = project / "draft_meta_info.json"
    if meta_path.exists():
        m = json.loads(meta_path.read_text("utf-8"))
        m["draft_name"] = name
        m["draft_fold_path"] = str(project).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS).replace("\\", "/")
        meta_path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    # --- Add text labels via capcut-cli ---
    print(f"4. Adding labels...")
    for i, (label, _) in enumerate(effects):
        ts = i * SEG_S
        te = min((i + 1) * SEG_S, dur_sec)
        cmd(f'npx.cmd capcut-cli add-text "{project}" {ts}s {te - ts}s "{label}" --font-size 16 --color "#FF6B00" --align 1 --y -0.2 --track-name labels')

    print(f"\nProject ready: {project}")
    print(f"Keyframe properties: {len(all_kf_props)}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_fx4.py <video.mp4>")
        sys.exit(1)
    main()
