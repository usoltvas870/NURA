"""Build a CapCut short video from source video + script text.

Usage:
    python scripts/build_video.py <video.mp4> "<script text>"
    python scripts/build_video.py videos/media/my_clip.mp4 "NURA is an AI agent platform"
"""

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = NURA_ROOT / "videos" / "template"
OUTPUT_DIR = NURA_ROOT / "videos" / "output"
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


def _probe_duration(path: Path) -> float:
    """Get video duration in seconds via ffmpeg -i."""
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


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(*args: str) -> dict:
    cmd = ["npx.cmd", "capcut-cli", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=NURA_ROOT,
        shell=True,
    )
    if result.returncode != 0:
        print(f"capcut-cli error: {result.stderr.strip()}")
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"capcut-cli output: {result.stdout}")
        return {}


def _generate_srt(script: str, words_per_sec: float = 2.5) -> str:
    words = script.split()
    total_dur = max(len(words) / words_per_sec, 2.0)
    lines = []
    chunk_size = max(1, len(words) // max(1, round(total_dur / 3)))
    chunks = [
        words[i : i + chunk_size]
        for i in range(0, len(words), chunk_size)
    ]
    dur_per_chunk = total_dur / len(chunks)
    start = 0.0
    for i, chunk in enumerate(chunks):
        end = start + dur_per_chunk
        lines.append(f"{i + 1}")
        lines.append(
            f"{_fmt_time(start)} --> {_fmt_time(end)}"
        )
        lines.append(" ".join(chunk))
        lines.append("")
        start = end
    return "\n".join(lines)


def _fmt_time(secs: float) -> str:
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _copy_template(dst: Path) -> None:
    """Recursively copy template, excluding bak/tmp."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(TEMPLATE_DIR, dst, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))


def build(
    video_path: str,
    script: str,
    project_name: str | None = None,
    open_capcut: bool = True,
) -> None:
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = project_name or f"nura_{uuid.uuid4().hex[:8]}"
    project_dir = DRAFTS_DIR / name

    _ensure_dir(OUTPUT_DIR)
    _copy_template(project_dir)

    project_id = str(uuid.uuid4()).upper()
    _patch_project(project_dir, project_id, name)

    dur_sec = _probe_duration(video)
    if dur_sec <= 0:
        print("Warning: could not detect video duration, assuming 10s")
        dur_sec = 10.0
    print(f"Video duration: {dur_sec:.1f}s")

    # capcut-cli needs forward slashes (uses .split("/") internally)
    print(f"Adding video: {video.name}")
    try:
        rel_path = video.relative_to(NURA_ROOT).as_posix()
    except ValueError:
        rel_path = video.as_posix()
    _run("add-video", str(project_dir), rel_path, "0", f"{dur_sec:.2f}s")

    print("Generating subtitles...")
    srt = _generate_srt(script, words_per_sec=max(2.0, len(script.split()) / dur_sec))
    srt_path = project_dir / "subtitles.srt"
    srt_path.write_text(srt, encoding="utf-8")
    print(srt)

    print("Importing SRT...")
    _run(
        "import-srt",
        str(project_dir),
        str(srt_path),
        "--color", "#FF6B00",
        "--font-size", "18",
        "--align", "1",
        "--y", "-0.15",
        "--track-name", "subtitles",
    )

    print(f"\nProject ready: {project_dir}")
    print(f"Duration: {dur_sec:.1f}s | Script: {len(script.split())} words")

    if open_capcut and CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


def _patch_project(project_dir: Path, project_id: str, name: str) -> None:
    meta_path = project_dir / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    meta["draft_id"] = project_id
    meta["draft_name"] = name
    meta["draft_fold_path"] = str(project_dir).replace("\\", "/")
    meta["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    content_path = project_dir / "draft_content.json"
    content = json.loads(content_path.read_text("utf-8"))
    content["id"] = project_id
    content["name"] = name
    content["duration"] = 0
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    tl_path = project_dir / "Timelines" / "project.json"
    if tl_path.exists():
        tl = json.loads(tl_path.read_text("utf-8"))
        tl["id"] = str(uuid.uuid4()).upper()
        tl["main_timeline_id"] = project_id
        tl_path.write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    build(video_path=sys.argv[1], script=sys.argv[2])
