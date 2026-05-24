"""Interactive scenario builder.

Usage:
    python scripts/create_scenario.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nura_app"))

NURA_ROOT = Path(__file__).resolve().parent.parent


def _pick_file(prompt: str, folder: str, pattern: str) -> str:
    folder_path = NURA_ROOT / folder
    files = sorted(folder_path.glob(pattern))
    if not files:
        print(f"  No files found in {folder}/")
        return input(f"  {prompt}: ").strip()
    print(f"  Available files in {folder}/:")
    for i, f in enumerate(files, 1):
        sz = f.stat().st_size / 1024 / 1024
        print(f"    [{i}] {f.name} ({sz:.0f} MB)")
    print("    [0] Enter custom path")
    choice = input(f"  Choose [{len(files)}]: ").strip()
    if choice.isdigit() and 0 < int(choice) <= len(files):
        return str(files[int(choice) - 1].relative_to(NURA_ROOT).as_posix())
    return input(f"  {prompt}: ").strip()


def _pick_videos(prompt: str) -> list[dict]:
    items = []
    while True:
        print(f"\n  {prompt}")
        src = _pick_file("Video path", "videos/media", "*.mp4")
        if not src:
            break
        start = float(input("    Start (sec): ") or "0")
        end = float(input("    End (sec): ") or "0")
        full = input("    Full screen? (Y/n): ").strip().lower()
        if full != "n":
            items.append({"type": "video", "src": src, "start": start, "end": end, "x": 0, "y": 0, "width": 1.0})
        else:
            x = float(input("    X pos (0-1): ") or "0.7")
            y = float(input("    Y pos (0-1): ") or "0.05")
            w = float(input("    Width (0-1): ") or "0.25")
            items.append({"type": "video", "src": src, "start": start, "end": end, "x": x, "y": y, "width": w})
        more = input("    Add another? (Y/n): ").strip().lower()
        if more == "n":
            break
    return items


def main():
    print("=== NURA Scenario Builder ===\n")

    name = input("Video name (no spaces): ").strip() or "nura_video"
    nura_video = _pick_file("Nura talking head video", "videos/media", "*.mp4")
    if not nura_video:
        nura_video = "videos/media/test.mp4"

    print("\n--- Subtitles ---")
    subs = input("Auto subtitles? (Y/n): ").strip().lower() != "n"
    font_size = int(input("Font size (50): ") or "50")

    overlays = []

    print("\n--- Zoom on face ---")
    zoom = input("Add zoom effect? (Y/n): ").strip().lower() != "n"
    if zoom:
        z_start = float(input("  Start (sec, default 2): ") or "2")
        z_dur = float(input("  Duration (sec, default 3): ") or "3")
        z_to = float(input("  Zoom to scale (1.12): ") or "1.12")
        overlays.append({"type": "zoom", "start": z_start, "duration": z_dur, "from_scale": 1.0, "to_scale": z_to})
        end_zoom = input("Add end zoom? (y/N): ").strip().lower() == "y"
        if end_zoom:
            ez_start = float(input("  End zoom start (sec): ") or "20")
            ez_dur = float(input("  End zoom duration (sec): ") or "4")
            ez_to = float(input("  End zoom to scale (1.18): ") or "1.18")
            overlays.append({"type": "zoom", "start": ez_start, "duration": ez_dur, "from_scale": 1.0, "to_scale": ez_to})

    stock_videos = _pick_videos("--- Stock videos ---")
    overlays.extend(stock_videos)

    print("\n--- Text overlay ---")
    text = input("Add text on screen? (y/N): ").strip().lower() == "y"
    if text:
        txt = input("  Text: ").strip()
        t_start = float(input("  Start (sec): ") or "0")
        t_end = float(input("  End (sec): ") or "3")
        t_x = float(input("  X pos 0-1 (0.5=center): ") or "0.5")
        t_y = float(input("  Y pos 0-1 (0.15=top): ") or "0.15")
        t_size = int(input("  Font size (56): ") or "56")
        overlays.append({"type": "text", "text": txt, "start": t_start, "end": t_end, "x": t_x, "y": t_y, "font_size": t_size, "color": "#FF6B00"})

    scenario = {
        "name": name,
        "nura_video": nura_video,
        "subtitles": {
            "enabled": subs,
            "mode": "auto" if subs else "manual",
            "font_size": font_size,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 3.0,
            "y_position": 0.7,
        },
        "scenes": [
            {
                "start": 0,
                "duration": 0,
                "overlays": overlays,
            }
        ],
    }

    out_dir = NURA_ROOT / "scenarios"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name}.json"
    out_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Done: {out_path} ===")
    print(f"Run: python scripts/assemble.py scenarios/{name}.json")


if __name__ == "__main__":
    main()
