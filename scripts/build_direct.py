"""
Build CapCut project: copy seed (0517), replace UUID everywhere,
update video path + add subtitles + change name/duration.
"""

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

NURA_ROOT = Path(__file__).resolve().parent.parent
SEED = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0517"
DRAFTS_DIR = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
CAPCUT_EXE = Path.home() / "AppData/Local/CapCut/Apps/CapCut.exe"


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _probe_duration(path: Path) -> float:
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


def _replace_id_in_files(project_dir: Path, old_id: str, new_id: str) -> None:
    for f in project_dir.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".srt", ".jpg", ".png", ".mp4"):
            continue
    for f in project_dir.rglob("*.json"):
        text = f.read_text("utf-8")
        if old_id in text:
            text = text.replace(old_id, new_id)
            f.write_text(text, encoding="utf-8")


def _copy_to_assets(video: Path, project_dir: Path) -> Path:
    dst = project_dir / "assets" / "video" / video.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, dst)
    return dst


def _generate_srt(text: str, dur: float) -> str:
    words = text.split()
    if not words:
        return ""
    chunk_s = 3.0
    n = max(1, round(dur / chunk_s))
    cs = max(1, len(words) // n)
    chunks = [words[i:i + cs] for i in range(0, len(words), cs)]
    dp = dur / len(chunks)
    lines, st = [], 0.0
    for i, c in enumerate(chunks):
        en = min(st + dp, dur)
        lines.append(str(i + 1))
        h1, m1, s1 = int(st // 3600), int((st % 3600) // 60), int(st % 60)
        ms1 = int((st - int(st)) * 1000)
        h2, m2, s2 = int(en // 3600), int((en % 3600) // 60), int(en % 60)
        ms2 = int((en - int(en)) * 1000)
        lines.append(f"{h1:02d}:{m1:02d}:{s1:02d},{ms1:03d} --> {h2:02d}:{m2:02d}:{s2:02d},{ms2:03d}")
        lines.append(" ".join(c))
        lines.append("")
        st = en
    return "\n".join(lines)


def _extract_old_id(project_dir: Path) -> str | None:
    root = project_dir / "draft_content.json"
    if root.exists():
        d = json.loads(root.read_text("utf-8"))
        return d.get("id")
    return None


def build(video_path: str, script: str, project_name: str | None = None) -> None:
    video = Path(video_path).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    name = project_name or f"nura_{uuid.uuid4().hex[:8]}"
    project_dir = DRAFTS_DIR / name
    new_id = _uid()

    if project_dir.exists():
        shutil.rmtree(project_dir)

    print("Copying seed (0517)...")
    shutil.copytree(SEED, project_dir, ignore=shutil.ignore_patterns("*.bak", "*.tmp"))

    old_id = _extract_old_id(project_dir)
    if not old_id:
        print("ERROR: no id found in seed draft_content.json")
        sys.exit(1)
    print(f"Replacing UUID: {old_id[:8]}... -> {new_id[:8]}...")

    _replace_id_in_files(project_dir, old_id, new_id)

    tl_subdir = project_dir / "Timelines" / old_id
    if tl_subdir.exists():
        shutil.move(str(tl_subdir), str(project_dir / "Timelines" / new_id))

    print("Copying video to assets...")
    local_path = _copy_to_assets(video, project_dir)

    dur_sec = _probe_duration(video)
    if dur_sec <= 0:
        dur_sec = 10.0
    dur_us = int(dur_sec * 1_000_000)

    print(f"Duration: {dur_sec:.1f}s")

    root_content = project_dir / "draft_content.json"
    dc = json.loads(root_content.read_text("utf-8"))

    dc["name"] = name
    dc["duration"] = dur_us

    for t in dc.get("tracks", []):
        if t.get("type") == "video":
            t["name"] = "video"
            for seg in t.get("segments", []):
                seg["target_timerange"] = {"start": 0, "duration": dur_us}
                seg["source_timerange"] = {"start": 0, "duration": dur_us}
                mat_id = seg.get("material_id")
                if mat_id:
                    for mat in dc.get("materials", {}).get("videos", []):
                        if mat.get("id") == mat_id:
                            mat["path"] = str(local_path)
                            mat["material_name"] = local_path.name
                            mat["duration"] = dur_us
                            mat["has_audio"] = True

    root_content.write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    meta = project_dir / "draft_meta_info.json"
    if meta.exists():
        m = json.loads(meta.read_text("utf-8"))
        m["draft_id"] = new_id
        m["draft_name"] = name
        m["draft_fold_path"] = str(project_dir).replace("\\", "/")
        m["draft_root_path"] = str(DRAFTS_DIR).replace("\\", "/")
        m["tm_duration"] = dur_us
        meta.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    print("Generating subtitles...")
    srt = _generate_srt(script, dur_sec)
    (project_dir / "subtitles.srt").write_text(srt, encoding="utf-8")

    text_mat_id = _uid()
    text_track_id = _uid()

    cues = []
    for blk in srt.strip().split("\n\n"):
        lines = blk.strip().split("\n")
        if len(lines) >= 3:
            time_line = lines[1]
            parts = time_line.split(" --> ")
            if len(parts) == 2:
                def to_us(t):
                    h, m, s_ms = t.split(":")
                    s, ms = s_ms.split(",")
                    return (int(h)*3600 + int(m)*60 + int(s))*1000000 + int(ms)*1000
                st = to_us(parts[0])
                en = to_us(parts[1])
                txt = "\n".join(lines[2:])
                cues.append((st, en, txt))

    text_material = {
        "id": text_mat_id,
        "type": "text",
        "content": json.dumps({
            "styles": [{
                "range": [0, len(cues[0][2].encode("utf-16-le"))] if cues else [0, 1],
                "size": 18, "bold": False, "italic": False, "underline": False,
                "fill": {"alpha": 1, "content": {"render_type": "solid", "solid": {"alpha": 1, "color": [1, 0.42, 0]}}},
            }],
            "text": cues[0][2] if cues else "",
        }),
        "duration": dur_us,
        "width": 1920, "height": 1080,
        "alignment": 1, "font_size": 18, "text_color": "#FF6B00",
    }
    dc["materials"]["texts"] = [text_material]

    text_track = {
        "id": text_track_id,
        "type": "text",
        "name": "subtitles",
        "attribute": 0,
        "segments": [],
        "is_default_name": False,
        "flag": 0,
    }

    for i, (st, en, txt) in enumerate(cues):
        seg = {
            "id": _uid(),
            "material_id": text_mat_id,
            "raw_segment_id": text_track_id,
            "target_timerange": {"start": st, "duration": en - st},
            "source_timerange": {"start": st, "duration": en - st},
            "speed": 1, "volume": 1, "visible": True, "reverse": False,
            "clip": {
                "alpha": 1, "rotation": 0,
                "scale": {"x": 1, "y": 1},
                "transform": {"x": 0, "y": -0.15},
                "flip": {"horizontal": False, "vertical": False},
            },
            "render_index": 12000 + i, "track_render_index": 0, "track_attribute": 0,
            "extra_material_refs": [],
            "common_keyframes": [], "keyframe_refs": [],
        }
        text_track["segments"].append(seg)

    dc["tracks"].append(text_track)
    root_content.write_text(json.dumps(dc, ensure_ascii=False), encoding="utf-8")

    print(f"\nProject ready: {project_dir}")

    if CAPCUT_EXE.exists():
        print("Opening CapCut...")
        subprocess.Popen([str(CAPCUT_EXE), str(project_dir)])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/build_direct.py <video.mp4> \"<script text>\"")
        sys.exit(1)
    build(video_path=sys.argv[1], script=sys.argv[2])
