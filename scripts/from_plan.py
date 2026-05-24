"""Parse content-plan CSV → scenario JSON → assemble video.

Usage:
    python scripts/from_plan.py plan.csv --video videos/media/main.mp4
    python scripts/from_plan.py plan.csv --video videos/media/main.mp4 --row TH_001
    python scripts/from_plan.py plan.csv --video videos/media/main.mp4 --search-stock
"""
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nura_app"))
from core.services.video_assembler import ScenarioConfig, assemble, NURA_ROOT


# ── column keys (single row, normalised in main) ──
# A=ID  B=Формат  C=Цель  D=Локация/Фон  E=Крючок  F=Скрипт
# G=Стоковые триггеры  H=Динамика/эффекты  I=Субтитры  J=Карусель

# ── helpers ──

def _ts_to_sec(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(ts)


def _parse_timeline(raw: str) -> list[dict]:
    if not raw or raw.strip() in ("", "-", "—", "Не применяется для этого видео"):
        return []
    entries = []
    parts = re.split(r"(\d+:\d+(?:\.\d+)?(?:-\d+:\d+(?:\.\d+)?)?)\s*[—–-]?\s*", raw)
    i = 1
    while i < len(parts) - 1:
        ts = parts[i].strip()
        desc = parts[i + 1].strip().rstrip(".").rstrip(".")
        if "-" in ts and not ts.startswith("-"):
            rp = ts.split("-", 1)
            start = _ts_to_sec(rp[0])
            dur = _ts_to_sec(rp[1]) - start
        else:
            start = _ts_to_sec(ts)
            dur = None
        entries.append({"time": start, "duration": dur, "desc": desc})
        i += 2
    return entries


def _parse_stock_triggers(raw: str) -> list[dict]:
    if not raw or raw.strip() in ("", "-"):
        return []
    triggers = []
    for m in re.finditer(r"([^:\[\]]+?)\s*:\s*\[([^\]]+)\]", raw):
        kws = [k.strip() for k in m.group(2).split(",") if k.strip()]
        triggers.append({"trigger": m.group(1).strip(), "keywords": kws})
    return triggers


def _get_subtitle_style(raw: str) -> dict:
    conf = {}
    if not raw or "Не применяется" in raw:
        return {"enabled": False}
    rl = raw.lower()
    if "центр" in rl:
        conf["y_position"] = 0.7
    conf["font_size"] = 50
    conf["color"] = "#FFD700" if ("золотой" in rl or "gold" in rl) else "#FFFFFF"
    if "белый" in rl:
        conf["color"] = "#FFFFFF"
    conf["stroke_color"] = "#000000"
    conf["stroke_width"] = 3.0
    return conf


def _estimate_trigger_time(trigger_text: str, script: str, total_dur: float) -> float:
    words = script.split()
    tw = trigger_text.split()
    if not words or not tw:
        return total_dur * 0.5
    for i, w in enumerate(words):
        if tw[0].lower() in w.lower():
            return round(total_dur * i / len(words), 1)
    return total_dur * 0.5


def _split_script_to_sentences(script: str) -> list[str]:
    """Split script by sentence boundaries, not raw word count."""
    segs = re.split(r"(?<=[.!?])\s+", script)
    return [s.strip() for s in segs if s.strip()]


# ── format-specific builders ──

def _build_type1(row: dict, total_dur: float, stock_cache: dict | None) -> list[dict]:
    """Говорящая голова + zoom/transition + PiP stocks."""
    script = row.get("F", "")
    hook = row.get("E", "")
    timeline = _parse_timeline(row.get("H", ""))
    triggers = _parse_stock_triggers(row.get("G", ""))

    if not timeline:
        scenes = [{"start": 0, "duration": 0, "nura_text": script,
                    "overlays": [], "transition": None}]
    else:
        scenes = []
        for i, e in enumerate(timeline):
            t = e["time"]
            dur = e["duration"] or (timeline[i + 1]["time"] - t if i + 1 < len(timeline) else total_dur - t)
            if dur <= 0:
                continue
            desc = e["desc"].lower()
            sc = {"start": t, "duration": dur, "nura_text": None,
                  "overlays": [], "transition": None}

            if i > 0 and any(k in desc for k in ["переход", "transition", "blur", "dissolve"]):
                sc["transition"] = {"type": "fade", "duration": 0.5}

            if any(k in desc for k in ["zoom", "наезд", "punch"]):
                zt = "linear" if any(k in desc for k in ["slow", "медлен"]) else "cubic-in-out"
                ts = 1.15 if any(k in desc for k in ["punch", "резк"]) else 1.08
                sc["overlays"].append({
                    "type": "zoom", "start": 0,
                    "duration": min(dur, 2.0),
                    "from_scale": 1.0, "to_scale": ts, "easing": zt,
                })

            # stock overlay (PiP)
            stock_added = False
            if any(k in desc for k in ["сток", "stock"]) and triggers:
                for st in triggers:
                    st_ts = _estimate_trigger_time(st["trigger"], script, total_dur)
                    if abs(st_ts - t) < 5.0 or not stock_added:
                        kw = "_".join(st["keywords"][:2]).lower()
                        sp = stock_cache.get(kw) if stock_cache else None
                        if sp:
                            sc["overlays"].append({
                                "type": "video", "src": sp,
                                "start": 2, "end": min(dur, 8.0),
                                "x": 0.5, "y": 0, "width": 0.35,
                            })
                        stock_added = True
                        break
            if any(k in desc for k in ["сток", "stock"]) and not stock_added:
                print(f"  ⚠ No stock matched at {t}s")

            scenes.append(sc)

    # assign script by sentences
    sents = _split_script_to_sentences(script)
    if sents:
        if len(sents) >= len(scenes):
            for i, sc in enumerate(scenes):
                sc["nura_text"] = sents[i] if i < len(sents) else sents[-1]
        else:
            w_per = max(1, len(script.split()) // len(scenes))
            words = script.split()
            idx = 0
            for sc in scenes:
                chunk = words[idx: idx + w_per]
                sc["nura_text"] = " ".join(chunk) if chunk else None
                idx += w_per
            if idx < len(words):
                scenes[-1]["nura_text"] = (scenes[-1].get("nura_text", "") + " " + " ".join(words[idx:])).strip()
        scenes[-1]["nura_text"] = script  # full script for Whisper accuracy

    # hook text
    if hook and scenes:
        scenes[0]["overlays"].insert(0, {
            "type": "text", "text": hook.strip("«»\""),
            "start": 0, "end": 4.0, "x": 0, "y": -0.3,
            "font_size": 36, "color": "#FFD700",
        })

    return scenes


def _build_type2(row: dict, stock_cache: dict | None) -> list[dict]:
    """Фон + текст (стихи/мудрые слова)."""
    script = row.get("F", "")
    hook = row.get("E", "")
    triggers = _parse_stock_triggers(row.get("G", ""))

    # find background video
    bg = None
    if triggers and stock_cache:
        kw = "_".join(triggers[0]["keywords"][:2]).lower()
        bg = stock_cache.get(kw)

    if not bg:
        bg = "videos/media/TH_001.mp4"  # fallback

    # estimate duration from text length (~3 words/sec)
    est_dur = max(5, len(script.split()) / 3)

    overlays = []
    if hook:
        overlays.append({
            "type": "text", "text": hook.strip("«»\""),
            "start": 0, "end": 4.0, "x": 0, "y": -0.35,
            "font_size": 42, "color": "#FFD700",
        })
    if script:
        overlays.append({
            "type": "text", "text": script,
            "start": 3, "end": est_dur, "x": 0, "y": 0.05,
            "font_size": 32, "color": "#FFFFFF",
        })

    return [{
        "start": 0, "duration": est_dur,
        "nura_text": script,
        "overlays": overlays,
        "transition": None,
    }]


def _build_type3(row: dict) -> list[dict]:
    """Пергамент — фоновое видео + текст по фразам + тёплая цветокоррекция."""
    script = row.get("F", "")
    hook = row.get("E", "")

    est_dur = max(5, len(script.split()) / 3)
    hook_dur = 4.0
    sentences = _split_script_to_sentences(script) if script else []
    body_dur = max(1, est_dur - hook_dur)

    overlays = []
    if hook:
        overlays.append({
            "type": "text", "text": hook.strip("«»\""),
            "start": 0, "end": hook_dur,
            "x": 0, "y": -0.35,
            "font_size": 42, "color": "#FFD700",
        })

    if sentences:
        dur_per = body_dur / len(sentences)
        for i, sent in enumerate(sentences):
            start_t = hook_dur + i * dur_per
            end_t = hook_dur + (i + 1) * dur_per
            overlays.append({
                "type": "text", "text": sent,
                "start": round(start_t, 1),
                "end": round(end_t, 1),
                "x": 0, "y": 0.05,
                "font_size": 32, "color": "#FFFFFF",
            })

    return [{
        "start": 0,
        "duration": est_dur,
        "nura_text": script,
        "overlays": overlays,
        "transition": None,
        "color_grading": {
            "enabled": True,
            "shadows_red": 0.08,
            "shadows_green": 0.02,
            "midtones_red": 0.12,
            "midtones_green": 0.06,
            "midtones_blue": -0.04,
            "highlights_red": 0.05,
            "highlights_green": 0.02,
        },
    }]


# ── main builder ──

def _build_scenario(row: dict, video_path: str, total_duration: float,
                    stock_cache: dict | None = None) -> dict:
    fmt = (row.get("B", "") or "").lower()

    if "пергамент" in fmt or "тип 3" in fmt:
        scenes = _build_type3(row)
        sub_enabled = False
    elif "фон" in fmt or "тип 2" in fmt or "текст" in fmt:
        scenes = _build_type2(row, stock_cache)
        sub_enabled = False
    else:
        scenes = _build_type1(row, total_duration, stock_cache)
        sub_enabled = True

    sub_conf = _get_subtitle_style(row.get("I", ""))
    sub_conf["enabled"] = sub_conf.get("enabled", True) and sub_enabled

    return {
        "name": (row.get("A", "") or "nura_video").strip().lower(),
        "nura_video": video_path,
        "subtitles": {
            "enabled": sub_conf["enabled"],
            "mode": "auto",
            "font_size": sub_conf.get("font_size", 50),
            "color": sub_conf.get("color", "#FFFFFF"),
            "stroke_color": sub_conf.get("stroke_color", "#000000"),
            "stroke_width": sub_conf.get("stroke_width", 3.0),
            "y_position": sub_conf.get("y_position", 0.7),
        },
        "scenes": scenes,
    }


def _parse_carousel(raw: str) -> dict | None:
    """Parse column J — Instagram carousel directive.

    Uses DeepSeek via AIService.chat() with carousel_parser.txt prompt.
    Returns parsed CarouselConfig dict, or {"raw": raw} as fallback.
    """
    if not raw or "Не применяется" in raw or raw.strip() in ("", "-"):
        return None

    from core.services.ai import AIService

    prompt = AIService._load_prompt("carousel_parser.txt")
    if not prompt:
        return {"raw": raw, "type": "carousel"}

    async def _parse():
        try:
            response = await AIService.chat(
                [
                    {
                        "role": "system",
                        "content": "Ты — парсер каруселей для Instagram. Отвечай только JSON.",
                    },
                    {"role": "user", "content": prompt + "\n\n" + raw},
                ],
                api_params={"temperature": 0.1, "max_tokens": 4000},
            )
            parsed = await AIService._parse_json_response(response)
            if "error" in parsed:
                return {"raw": raw, "type": "carousel"}
            return parsed
        except Exception:
            return {"raw": raw, "type": "carousel"}

    return asyncio.run(_parse())


# ── main ──

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build video from content-plan CSV")
    ap.add_argument("csv", help="CSV export from Google Sheets")
    ap.add_argument("--row", help="Process specific video ID only")
    ap.add_argument("--video", help="Path to Nura talking-head video (for Type 1)")
    ap.add_argument("--output", help="Output scenario JSON path")
    ap.add_argument("--match-stock", action="store_true", default=True,
                    help="Match stock by local filenames (default)")
    ap.add_argument("--search-stock", action="store_true",
                    help="Auto-download stock via Pexels API")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("Empty CSV")
        sys.exit(1)

    print(f"Loaded {len(rows)} video(s)")

    media_dir = NURA_ROOT / "videos" / "media"

    def _norm(r: dict) -> dict:
        out = {}
        for k, v in r.items():
            letter = k.split(".")[0].strip()
            out[letter] = v
            out[k] = v
        return out

    for row_raw in rows:
        row = _norm(row_raw)
        vid = row.get("A", "").strip()
        if args.row and vid != args.row:
            continue
        if not vid:
            continue

        fmt = (row.get("B", "") or "").lower()
        print(f"\n--- {vid} [{row.get('B', '?')}] ---")

        # detect format
        is_type3 = "пергамент" in fmt or "тип 3" in fmt
        is_type2 = not is_type3 and ("фон" in fmt or "текст" in fmt or "тип 2" in fmt)

        # video path
        if is_type3:
            video_path = "videos/media/parchment.mp4"  # единый фон пергамента
        elif is_type2:
            video_path = args.video or "videos/media/TH_001.mp4"  # placeholder, будет заменён стоком
        else:
            video_path = args.video
            if not video_path:
                print("  ✗ --video required for Type 1")
                continue

        # probe duration
        from core.services.video_assembler import _probe_duration
        vp = Path(video_path)
        if not vp.is_absolute():
            vp = NURA_ROOT / vp
        if not vp.exists():
            print(f"  ✗ Video not found: {vp}")
            continue
        total_dur = _probe_duration(vp.resolve())
        rel_video = str(vp.relative_to(NURA_ROOT))

        # match stock
        stock_cache = None
        triggers = _parse_stock_triggers(row.get("G", ""))
        if triggers:
            if args.match_stock:
                from core.services.stock_media import match_local_stock
                stock_cache = match_local_stock(triggers, media_dir)
            if args.search_stock and (not stock_cache or len(stock_cache) < len(triggers)):
                from core.services.stock_media import search_stock_video
                for st in triggers:
                    kw = "_".join(st["keywords"][:2]).lower()
                    if stock_cache and kw in stock_cache:
                        continue
                    print(f"  🔍 Auto-search: {st['keywords']}")
                    p = search_stock_video(st["keywords"], str(media_dir))
                    if p:
                        stock_cache[kw] = str(p.relative_to(NURA_ROOT))

        scenario = _build_scenario(row, rel_video, total_dur, stock_cache)

        # save scenario
        out_name = args.output or f"scenarios/{vid.lower()}.json"
        out_path = Path(out_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Scenario -> {out_path}")

        # validate + assemble
        cfg = ScenarioConfig.model_validate(scenario)
        output = assemble(cfg)
        print(f"  Output: {output}")

        # carousel directive
        car = _parse_carousel(row.get("J", ""))
        if car:
            car_path = out_path.with_suffix(".carousel.json")
            car_path.write_text(json.dumps(car, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  Carousel directive -> {car_path}")
            if "slides" in car:
                from core.schemas.carousel import CarouselConfig
                from core.services.carousel_assembler import CarouselAssembler

                cfg = CarouselConfig.model_validate(car)
                pngs = asyncio.run(CarouselAssembler.assemble(cfg))
                print(f"  Generated {len(pngs)} slide(s)")


if __name__ == "__main__":
    main()
