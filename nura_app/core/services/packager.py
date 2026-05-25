import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContentPackage:
    job_id: str
    output_dir: Path

    video_path: Path | None = None
    carousel_paths: list[Path] = None
    caption_path: Path | None = None
    hashtags_path: Path | None = None
    publish_notes_path: Path | None = None
    brief_copy_path: Path | None = None

    def __post_init__(self):
        if self.carousel_paths is None:
            self.carousel_paths = []


def build_package(
    job_dir: Path,
    video_path: Path | None = None,
    carousel_dir: Path | None = None,
) -> ContentPackage:
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pkg = ContentPackage(job_id=job_dir.name, output_dir=output_dir)

    if video_path and video_path.exists():
        dest = output_dir / f"final_{job_dir.name}.mp4"
        shutil.copy2(video_path, dest)
        pkg.video_path = dest

    if carousel_dir and carousel_dir.exists():
        carousel_dest = output_dir / "carousel"
        carousel_dest.mkdir(parents=True, exist_ok=True)
        for png in sorted(carousel_dir.glob("*.png")):
            dest = carousel_dest / png.name
            shutil.copy2(png, dest)
            pkg.carousel_paths.append(dest)

    brief_path = job_dir / "input" / "brief.json"
    if brief_path.exists():
        dest = output_dir / "source_brief.json"
        shutil.copy2(brief_path, dest)
        pkg.brief_copy_path = dest

    caption, hashtags = _extract_text_content(job_dir)
    if caption:
        pkg.caption_path = _write_text(output_dir, "caption.txt", caption)
    if hashtags:
        pkg.hashtags_path = _write_text(output_dir, "hashtags.txt", hashtags)

    notes = _build_publish_notes(job_dir, pkg)
    pkg.publish_notes_path = _write_text(output_dir, "publish_notes.md", notes)

    return pkg


def _extract_text_content(job_dir: Path) -> tuple[str, str]:
    caption = ""
    hashtags = ""

    brief_path = job_dir / "input" / "brief.json"
    if brief_path.exists():
        try:
            brief = json.loads(brief_path.read_text("utf-8"))
            caption = brief.get("draft_description", "")
            hashtags = " ".join(brief.get("hashtags", []))
        except (json.JSONDecodeError, OSError):
            pass

    scenario_path = job_dir / "input" / "scenario.json"
    if not caption and scenario_path.exists():
        try:
            raw = json.loads(scenario_path.read_text("utf-8"))
            scenes = raw.get("scenes", [])
            all_text = " ".join(s.get("nura_text", "") for s in scenes)
            if all_text:
                caption = all_text[:2000]
        except (json.JSONDecodeError, OSError):
            pass

    return caption, hashtags


def _build_publish_notes(job_dir: Path, pkg: ContentPackage) -> str:
    lines = [
        f"# Publish Notes — {pkg.job_id}",
        "",
        "## Files",
    ]

    if pkg.video_path:
        lines.append(f"- Video: `{pkg.video_path.name}`")
    if pkg.carousel_paths:
        lines.append(f"- Carousel: {len(pkg.carousel_paths)} slides")
    if pkg.caption_path:
        lines.append(f"- Caption: `{pkg.caption_path.name}`")
    if pkg.hashtags_path:
        lines.append(f"- Hashtags: `{pkg.hashtags_path.name}`")

    brief_path = job_dir / "input" / "brief.json"
    if brief_path.exists():
        try:
            brief = json.loads(brief_path.read_text("utf-8"))
            lines.append("")
            lines.append("## Brief")
            lines.append(f"- Topic: {brief.get('topic', 'N/A')}")
            lines.append(f"- Format: {brief.get('recommended_format', 'N/A')}")
            lines.append(f"- Tone: {brief.get('tone', 'N/A')}")
            lines.append(f"- Original: {brief.get('url', 'N/A')}")
            lines.append(f"- Hook: {brief.get('hook_type', 'N/A')}")
            lines.append(f"- Pain point: {brief.get('pain_point', 'N/A')}")
        except (json.JSONDecodeError, OSError):
            pass

    lines.append("")
    lines.append("## Checklist")
    lines.append("- [ ] Video reviewed (audio, subtitles, transitions)")
    lines.append("- [ ] Caption edited")
    lines.append("- [ ] Hashtags verified")
    lines.append("- [ ] Carousel reviewed (if applicable)")
    lines.append("- [ ] Scheduled / Published")

    return "\n".join(lines)


def _write_text(output_dir: Path, name: str, content: str) -> Path:
    path = output_dir / name
    path.write_text(content, encoding="utf-8")
    return path
