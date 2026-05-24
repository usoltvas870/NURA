"""CapCut — все эффекты через capcut-cli (исправленные KFType* имена)."""

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


def init_project(name: str) -> Path:
    cmd(f'npx.cmd capcut-cli init {name} --template {TEMPLATE} --drafts "{DRAFTS}"')
    p = DRAFTS / name
    if not p.exists():
        candidates = list(DRAFTS.glob(f"{name}*"))
        p = candidates[0] if candidates else p
    return p


def add_video(project: Path, video: Path, dur_s: float):
    cmd(f'npx.cmd capcut-cli add-video "{project}" {video} 0 {dur_s:.2f}s')


def get_seg_id(project: Path) -> str:
    out = cmd(f'npx.cmd capcut-cli segments "{project}" --track video')
    segs = json.loads(out)
    return segs[0]["id"]


def keyframe(project: Path, seg_id: str, prop: str, time_s: float, value: str):
    r = cmd(f'npx.cmd capcut-cli keyframe "{project}" {seg_id} {prop} {time_s}s {value}')
    if "error" in r:
        print(f"  keyframe error: {r}")


def add_text(project: Path, seg_id: str, start_s: float, dur_s: float, text: str):
    cmd(f'npx.cmd capcut-cli add-text "{project}" {start_s}s {dur_s}s "{text}" --font-size 16 --color "#FF6B00" --align 1 --y -0.2 --track-name labels')


def speed(project: Path, seg_id: str, val: str):
    r = cmd(f'npx.cmd capcut-cli speed "{project}" {seg_id} {val}')
    if "error" in r:
        print(f"  speed error: {r}")


def main():
    video_path = sys.argv[1]
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = f"nura_fx3_{uuid.uuid4().hex[:6]}"
    dur_sec = probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0

    print(f"1. Init project: {name}")
    project = init_project(name)
    print(f"   -> {project}")

    print(f"2. Add video ({dur_sec:.1f}s)")
    add_video(project, video, dur_sec)
    seg_id = get_seg_id(project)
    print(f"   seg_id={seg_id[:12]}...")

    # Effects schedule: (start_s, end_s, [(prop, value_at_start, value_at_end), ...], label)
    # Each effect gets its own segment via keyframe boundaries
    seg_len = dur_sec / 8
    effects = [
        ("Original", {}),
        ("Spin 360", {"rotation": ("0deg", "360deg")}),
        ("Fade Out", {"alpha": ("1", "0")}),
        ("Saturation", {"saturation": ("0", "100")}),
        ("Contrast", {"contrast": ("0", "100")}),
        ("Brightness", {"brightness": ("0", "100")}),
        ("Speed 2x", {}),
        ("Slow 0.5x", {}),
    ]

    # Lock values for all properties (applied to every segment at both boundaries)
    ALL_PROPS = {
        "uniform_scale": "1",
        "rotation": "0deg",
        "alpha": "1",
        "position_x": "0",
        "position_y": "0",
        "saturation": "0",
        "contrast": "0",
        "brightness": "0",
    }

    print(f"3. Applying keyframes ({len(effects)} segments)...")
    for i, (label, anim) in enumerate(effects):
        ts = i * seg_len
        te = min((i + 1) * seg_len, dur_sec)

        if label == "Speed 2x":
            speed(project, seg_id, "2.0")
        elif label == "Slow 0.5x":
            speed(project, seg_id, "0.5")

        for prop, lock_val in ALL_PROPS.items():
            if prop in anim:
                v_start, v_end = anim[prop]
                keyframe(project, seg_id, prop, ts, v_start)
                keyframe(project, seg_id, prop, te, v_end)
            else:
                keyframe(project, seg_id, prop, ts, lock_val)
                keyframe(project, seg_id, prop, te, lock_val)

        add_text(project, seg_id, ts, te - ts, label)
        print(f"   {i}: {label} ({ts:.0f}s-{te:.0f}s)")

    print(f"\nProject ready: {project}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project)])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_fx3.py <video.mp4>")
        sys.exit(1)
    main()
