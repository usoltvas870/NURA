"""CapCut demo — чиним Timelines UUID mismatch."""

import json
import shutil
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


def fix_timelines(project_dir: Path) -> str:
    """Fix UUID mismatch between draft_content.json and Timelines subdir. Returns project UUID."""
    dc = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    new_id = dc.get("id", "")
    if not new_id:
        return ""

    tl_dir = project_dir / "Timelines"
    old_id = None

    # Find old UUID in Timelines subdirs
    for sub in tl_dir.iterdir():
        if sub.is_dir():
            old_id = sub.name
            break

    if not old_id or old_id == new_id:
        return new_id

    # Replace old UUID with new UUID in all JSON files
    for f in project_dir.rglob("*.json"):
        text = f.read_text("utf-8")
        if old_id in text:
            text = text.replace(old_id, new_id)
            f.write_text(text, encoding="utf-8")

    # Rename timeline subdir
    old_path = tl_dir / old_id
    new_path = tl_dir / new_id
    if old_path.exists():
        if new_path.exists():
            shutil.rmtree(new_path)
        shutil.move(str(old_path), str(new_path))

    return new_id


def main():
    video_path = sys.argv[1]
    video = Path(video_path)
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0

    name = f"nura_working_{uuid.uuid4().hex[:6]}"

    print(f"1. Init: {name}")
    cmd(f'npx.cmd capcut-cli init {name} --template {TEMPLATE} --drafts "{DRAFTS}"')

    project_dir = DRAFTS / name
    if not project_dir.exists():
        candidates = list(DRAFTS.glob(f"{name}*"))
        project_dir = candidates[0] if candidates else project_dir

    print("2. Fix Timelines UUID...")
    new_id = fix_timelines(project_dir)
    print(f"   project_id={new_id[:8]}, timelines synced")

    print(f"3. Add video ({dur_sec:.1f}s)...")
    cmd(f'npx.cmd capcut-cli add-video "{project_dir}" {video} 0 {dur_sec:.2f}s')

    # Get seg ID
    seg_out = cmd(f'npx.cmd capcut-cli segments "{project_dir}" --track video')
    try:
        segs = json.loads(seg_out)
        seg_id = segs[0]["id"]
    except Exception:
        print(f"   seg parse error: {seg_out[:200]}")
        sys.exit(1)
    print(f"   seg_id={seg_id[:12]}...")

    # Apply effects
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

    print("4. Applying keyframes...")
    for idx, (label, props) in enumerate(effects):
        ts = idx * SEG
        te = min((idx + 1) * SEG, dur_sec)

        if label == "Speed 2x":
            cmd(f'npx.cmd capcut-cli speed "{project_dir}" {seg_id} 2.0')
        elif label == "Slow 0.5x":
            cmd(f'npx.cmd capcut-cli speed "{project_dir}" {seg_id} 0.5')

        for prop, v_start, v_end in props:
            cmd(f'npx.cmd capcut-cli keyframe "{project_dir}" {seg_id} {prop} {ts}s {v_start}')
            cmd(f'npx.cmd capcut-cli keyframe "{project_dir}" {seg_id} {prop} {te}s {v_end}')

        # Lock position/scale at segment boundaries
        for lock_prop, lock_val in [("uniform_scale", "1"), ("position_x", "0"), ("position_y", "0")]:
            cmd(f'npx.cmd capcut-cli keyframe "{project_dir}" {seg_id} {lock_prop} {ts}s {lock_val}')
            cmd(f'npx.cmd capcut-cli keyframe "{project_dir}" {seg_id} {lock_prop} {te}s {lock_val}')

        cmd(f'npx.cmd capcut-cli add-text "{project_dir}" {ts}s {te - ts}s "{label}" --font-size 16 --color "#FF6B00" --align 1 --y -0.2 --track-name labels')
        print(f"   {label} ({ts:.0f}s-{te:.0f}s)")

    # Syncing timeline subdir after all changes
    dc_upd = json.loads((project_dir / "draft_content.json").read_text("utf-8"))
    tl_dc_path = project_dir / "Timelines" / new_id / "draft_content.json"
    if tl_dc_path.exists():
        tldc = json.loads(tl_dc_path.read_text("utf-8"))
        tldc["tracks"] = dc_upd["tracks"]
        tldc["materials"] = dc_upd["materials"]
        tldc["duration"] = dc_upd["duration"]
        tldc["name"] = dc_upd["name"]
        tl_dc_path.write_text(json.dumps(tldc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_working.py <video.mp4>")
        sys.exit(1)
    main()
