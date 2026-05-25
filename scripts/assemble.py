"""Nura video assembler.

Usage:
    python scripts/assemble.py scenarios/my_video.json
    python scripts/assemble.py scenarios/my_video.json --output my_video.mp4
    python scripts/assemble.py jobs/job_name   # job dir mode
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

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Not found: {target}")
        sys.exit(1)

    if target.is_dir():
        scenario_path = target / "input" / "scenario.json"
        if not scenario_path.exists():
            print(f"No scenario.json in {target}")
            sys.exit(1)
        raw = json.loads(scenario_path.read_text("utf-8"))
        config = ScenarioConfig.model_validate(raw)
        output = assemble(config, job_dir=target)
    else:
        raw = json.loads(target.read_text("utf-8"))
        config = ScenarioConfig.model_validate(raw)
        output = assemble(config)

    print(f"Output: {output}")


if __name__ == "__main__":
    main()
