"""CapCut — все эффекты. Копия seed 0517 + replace_uuid (как в build_zoom_kf.py)."""

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


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_effx_{uuid.uuid4().hex[:6]}"
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
    print(f"2. Replace UUID: {old_id[:8]} -> {new_id[:8]}")
    replace_all_uuids(project_dir, old_id, new_id)

    print(f"3. Copy video...")
    local_path = project_dir / "assets" / "video" / video.name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, local_path)

    # Update root draft_content.json
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    dc["name"] = name
    dc["duration"] = dur_us

    # Get seed video material and update path
    for mat in dc.get("materials", {}).get("videos", []):
        mat["path"] = str(local_path)
        mat["material_name"] = local_path.name
        mat["duration"] = dur_us
        mat["width"] = 1920
        mat["height"] = 1080

    # Use existing seed track — just update duration
    for t in dc.get("tracks", []):
        if t.get("type") == "video":
            for s in t.get("segments", []):
                s["target_timerange"] = {"start": 0, "duration": dur_us}
                s["source_timerange"] = {"start": 0, "duration": dur_us}

    (project_dir / "draft_content.json").write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    # Sync Timeline subdir
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

    # Get segment ID for keyframes
    seg_id = dc["tracks"][0]["segments"][0]["id"]
    print(f"4. segment_id={seg_id[:12]}...")

    # Apply keyframes via capcut-cli
    SEG = dur_sec / 8
    effects = [
        ("Original",        []),
        ("Spin 360",        [("rotation", "0deg", "360deg")]),
        ("Fade Out",        [("alpha", "1", "0")]),
        ("Saturation",      [("saturation", "0", "100")]),
        ("Contrast",        [("contrast", "0", "100")]),
        ("Brightness",      [("brightness", "0", "100")]),
        ("Speed 2x",        []),
        ("Slow 0.5x",       []),
    ]

    def capcut_cli(*args: str) -> None:
        r = subprocess.run(["npx.cmd", "capcut-cli", *args], capture_output=True, text=True, cwd=NURA_ROOT, shell=True)

    print(f"5. Keyframes...")
    for idx, (label, props) in enumerate(effects):
        ts = idx * SEG
        te = min((idx + 1) * SEG, dur_sec)

        if label == "Speed 2x":
            capcut_cli("speed", str(project_dir), seg_id, "2.0")
        elif label == "Slow 0.5x":
            capcut_cli("speed", str(project_dir), seg_id, "0.5")

        for prop, v_start, v_end in props:
            capcut_cli("keyframe", str(project_dir), seg_id, prop, f"{ts}s", v_start)
            capcut_cli("keyframe", str(project_dir), seg_id, prop, f"{te}s", v_end)

        for lock_prop, lock_val in [("uniform_scale", "1"), ("position_x", "0"), ("position_y", "0")]:
            capcut_cli("keyframe", str(project_dir), seg_id, lock_prop, f"{ts}s", lock_val)
            capcut_cli("keyframe", str(project_dir), seg_id, lock_prop, f"{te}s", lock_val)

        capcut_cli("add-text", str(project_dir), f"{ts}s", f"{te - ts}s", label,
                   "--font-size", "16", "--color", "#FF6B00", "--align", "1", "--y", "-0.2", "--track-name", "labels")
        print(f"   {label} ({ts:.0f}s-{te:.0f}s)")

    # Final sync: copy root → Timeline subdir
    dc_final = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    if tl_content.exists():
        tldc = json.loads(tl_content.read_text("utf-8"))
        tldc["tracks"] = dc_final["tracks"]
        tldc["materials"] = dc_final["materials"]
        tldc["duration"] = dc_final["duration"]
        tldc["name"] = dc_final["name"]
        tl_content.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_effx.py <video.mp4>")
        sys.exit(1)
    main()
