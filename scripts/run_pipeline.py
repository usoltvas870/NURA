"""NURA Video Production Pipeline.

Двухэтапный конвейер:
  Этап 1 (--dry-run): тренды → AI → JSON-сценарии
  Этап 2: JSON-сценарии → сборка видео

Usage:
    # Только генерация сценариев (режим A — полуавтомат)
    python scripts/run_pipeline.py --dry-run

    # Генерация + сборка (если все файлы готовы)
    python scripts/run_pipeline.py

    # Из конкретного файла трендов
    python scripts/run_pipeline.py --from-trend ../nura-trend-radar/data/trend_top.json

    # Только топ-3
    python scripts/run_pipeline.py --top 3

    # Валидация сгенерированных сценариев после dry-run
    python scripts/run_pipeline.py --validate
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nura_app"))

from core.services.video_pipeline import VideoPipeline, NURA_ROOT


async def main():
    parser = argparse.ArgumentParser(description="NURA Video Production Pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Этап 1: только генерация JSON-сценариев (без сборки)")
    parser.add_argument("--top", type=int, default=10,
                        help="Количество видео для обработки (по умолч. 10)")
    parser.add_argument("--from-trend", type=str, default=None,
                        help="Путь к trend_top.json (если не указан — ищет в nura-trend-radar/data/)")
    parser.add_argument("--validate", action="store_true",
                        help="Проверить валидность всех сценариев в scenarios/")
    parser.add_argument("--assemble", action="store_true",
                        help="Этап 2: собрать видео по всем сценариям (после dry-run)")
    parser.add_argument("--to-xlsx", action="store_true",
                        help="Экспортировать все JSON-сценарии в Excel для просмотра")

    args = parser.parse_args()

    if args.validate:
        _validate_all()
        return

    if args.to_xlsx:
        _export_xlsx()
        return

    pipeline = VideoPipeline(
        trend_data_path=args.from_trend,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("=" * 60)
        print("  NURA Pipeline — Этап 1: генерация сценариев (dry-run)")
        print("=" * 60)
        generated = await pipeline.run(top_n=args.top)

        print(f"\nСгенерировано сценариев: {len(generated)}")
        for p in generated:
            valid = pipeline.validate_scenario(p)
            print(f"  {'✓' if valid else '✗'} {p.name}")

        print("\nДалее:")
        print("  1. Запиши видео Нуры по текстам из nura_text")
        print("  2. Скачай стоковые видео по source_keywords в videos/media/")
        print("  3. Подправь JSON если нужно")
        print("  4. Запусти: python scripts/run_pipeline.py")
        print("     (или python scripts/assemble.py scenarios/имя.json для одного видео)")
    else:
        if args.assemble:
            print("=" * 60)
            print("  NURA Pipeline — Этап 2: сборка видео")
            print("=" * 60)
            pipeline.generated = list((NURA_ROOT / "scenarios").glob("*.json"))
            pipeline.dry_run = False
            outputs = await pipeline.assemble_all()
            print(f"\nСобрано видео: {len(outputs)}")
            for o in outputs:
                print(f"  ✓ {o}")
        else:
            print("=" * 60)
            print("  NURA Pipeline — полный цикл")
            print("=" * 60)
            generated = await pipeline.run(top_n=args.top)
            outputs = await pipeline.assemble_all()
            print(f"\nГотово: {len(outputs)} видео")
            for o in outputs:
                print(f"  ✓ {o}")


def _validate_all():
    scenarios_dir = NURA_ROOT / "scenarios"
    from core.services.video_assembler import ScenarioConfig

    files = sorted(scenarios_dir.glob("*.json"))
    if not files:
        print("Нет файлов сценариев в scenarios/")
        return

    print(f"Валидация {len(files)} сценариев...")
    ok = 0
    for p in files:
        try:
            raw = json.loads(p.read_text("utf-8"))
            ScenarioConfig.model_validate(raw)
            print(f"  ✓ {p.name}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {p.name}: {e}")
    print(f"\nВалидных: {ok}/{len(files)}")


def _export_xlsx():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
    except ImportError:
        print("Установи openpyxl: pip install openpyxl")
        return

    scenarios_dir = NURA_ROOT / "scenarios"
    files = sorted(scenarios_dir.glob("*.json"))
    if not files:
        print("Нет файлов сценариев в scenarios/")
        return

    out_dir = NURA_ROOT / "videos" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scenarios_view.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Сценарии NURA"

    headers = [
        ("Файл", 30), ("Сцена", 8), ("Старт", 10), ("Длит.", 10),
        ("Переход", 20), ("Текст озвучки (nura_text)", 70),
        ("Ключевые слова стока", 35), ("Оверлеи", 50),
        ("Цветокоррекция", 20),
    ]

    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill(start_color="1A1A1A", end_color="1A1A1A", fill_type="solid")
    cell_align = Alignment(vertical="top", wrap_text=True)

    for col, (name, w) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[chr(64 + col)].width = w

    row = 2
    for fp in files:
        try:
            raw = json.loads(fp.read_text("utf-8"))
        except Exception:
            continue
        scenes = raw.get("scenes", [])
        if not scenes:
            ws.cell(row=row, column=1, value=fp.name)
            ws.cell(row=row, column=6, value="(нет сцен)")
            for c in range(1, len(headers) + 1):
                ws.cell(row=row, column=c).alignment = cell_align
            row += 1
        for si, sc in enumerate(scenes, 1):
            ws.cell(row=row, column=1, value=fp.name)
            ws.cell(row=row, column=2, value=si)
            ws.cell(row=row, column=3, value=sc.get("start", 0))
            ws.cell(row=row, column=4, value=sc.get("duration", ""))
            tr = sc.get("transition")
            ws.cell(row=row, column=5, value=f"{tr['type']} / {tr['duration']}s" if tr else "")
            ws.cell(row=row, column=6, value=sc.get("nura_text", ""))
            ws.cell(row=row, column=7, value=", ".join(sc.get("source_keywords", [])))
            ovs = []
            for ov in sc.get("overlays", []):
                t = ov.get("type", "")
                if t == "text":
                    ovs.append(f"text: {ov.get('text', '')} [{ov.get('start')}-{ov.get('end')}s]")
                elif t == "zoom":
                    ovs.append(f"zoom: {ov.get('from_scale')}→{ov.get('to_scale')} ({ov.get('easing')})")
                elif t == "video":
                    ovs.append(f"video: {ov.get('src', '')}")
                elif t == "image":
                    ovs.append(f"image: {ov.get('src', '')}")
            ws.cell(row=row, column=8, value="\n".join(ovs))
            cg = sc.get("color_grading", {})
            ws.cell(row=row, column=9, value="вкл" if cg.get("enabled") else "—")
            for c in range(1, len(headers) + 1):
                ws.cell(row=row, column=c).alignment = cell_align
            row += 1

    wb.save(str(out_path))
    print(f"Excel: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
