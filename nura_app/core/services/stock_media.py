"""Stock media service — local matching + optional API search.

Primary path: user uploads B-roll to videos/media/, we match by filename keywords.
Fallback: Pexels API search (requires PEXELS_API_KEY in .env).
"""
import re
from pathlib import Path

PEXELS_API_KEY = ""


def _sanitize(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:60]


def match_local_stock(triggers: list[dict], media_dir: Path) -> dict[str, str]:
    """Find uploaded stock files by keyword match on filenames.

    Scans media_dir for video files, matches each trigger's keywords
    against filename. Returns {keyword_key: relative_path}.
    """
    cache: dict[str, str] = {}
    exts = {".mp4", ".mov", ".avi", ".webm", ".mkv"}
    if not media_dir.exists():
        return cache

    files = [f for f in media_dir.iterdir() if f.suffix.lower() in exts]

    for st in triggers:
        kw_key = "_".join(st["keywords"][:2]).lower()
        if kw_key in cache:
            continue

        best = None
        best_score = 0
        kw_lower = [w.lower() for w in st["keywords"]]

        for f in files:
            fname = f.stem.lower()
            score = sum(1 for w in kw_lower if w in fname)
            if score > best_score:
                best_score = score
                best = f

        if best and best_score > 0:
            cache[kw_key] = str(best.relative_to(media_dir.parent.parent))
            print(f"  [OK] Stock: {st['keywords']} -> {cache[kw_key]}")
        else:
            print(f"  [--] Stock not found: {st['keywords']}")

    return cache


def search_stock_video(keywords: list[str], dest_dir: str = "videos/media") -> Path | None:
    """Auto-download stock via Pexels API (requires PEXELS_API_KEY)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    if PEXELS_API_KEY:
        path = _pexels_search(keywords, dest)
        if path:
            return path

    return None


def _pexels_search(keywords: list[str], dest: Path) -> Path | None:
    import requests
    query = "+".join(keywords[:3])
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
    try:
        r = requests.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        for video in data.get("videos", []):
            for file in video.get("video_files", []):
                if file.get("width") and file["width"] <= 1280:
                    dl_url = file["link"]
                    ext = Path(dl_url.split("?")[0]).suffix or ".mp4"
                    name = _sanitize("_".join(keywords[:2])) + ext
                    out = dest / name
                    if _download(dl_url, out):
                        return out
    except Exception:
        return None
    return None


def _download(url: str, dest: Path) -> bool:
    import requests
    try:
        r = requests.get(url, timeout=30, stream=True)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return dest.exists() and dest.stat().st_size > 1024
    except Exception:
        return False
