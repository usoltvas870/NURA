"""CLI to assemble carousel JSON config -> PNG slides.

Usage:
    python scripts/assemble_carousel.py scenarios/th_001.carousel.json
    python scripts/assemble_carousel.py scenarios/th_001.carousel.json --output custom_output
    python scripts/assemble_carousel.py --check
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nura_app"))
from core.schemas.carousel import CarouselConfig
from core.services.carousel_assembler import CarouselAssembler


def main():
    ap = argparse.ArgumentParser(description="Assemble carousel from JSON config")
    ap.add_argument("path", nargs="?", help="Path to .carousel.json file")
    ap.add_argument("--output", help="Custom output directory for PNGs")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Validate all *.carousel.json schemas",
    )
    args = ap.parse_args()

    if args.check:
        scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"
        carousel_files = sorted(scenarios_dir.glob("*.carousel.json"))
        if not carousel_files:
            print("No *.carousel.json files found")
            return
        for p in carousel_files:
            raw = json.loads(p.read_text("utf-8"))
            try:
                CarouselConfig.model_validate(raw)
                print(f"  [check] {p.name}")
            except Exception as e:
                print(f"  [fail] {p.name}: {e}")
        return

    if not args.path:
        ap.print_help()
        sys.exit(1)

    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    raw = json.loads(path.read_text("utf-8"))
    cfg = CarouselConfig.model_validate(raw)

    if args.output:
        CarouselAssembler.OUTPUT_DIR = Path(args.output)

    paths = asyncio.run(CarouselAssembler.assemble(cfg))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
