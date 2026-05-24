"""Nura video assembler.

Usage:
    python scripts/assemble.py scenarios/my_video.json
    python scripts/assemble.py scenarios/my_video.json --output my_video.mp4
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nura_app"))

from core.services.video_assembler import ScenarioConfig, assemble


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Scenario not found: {json_path}")
        sys.exit(1)

    raw = json.loads(json_path.read_text("utf-8"))
    config = ScenarioConfig.model_validate(raw)

    output = assemble(config)
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
