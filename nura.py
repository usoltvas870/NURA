"""NURA Content Pipeline - единая точка входа.

Usage:
    python nura.py radar         1  Сбор трендов TikTok
    python nura.py scenarios     2  AI -> JSON-сценарии для видео
    python nura.py carousels     3  AI -> карусели Instagram
    python nura.py xlsx          4  Сценарии -> Excel (для просмотра)
    python nura.py validate      5  Проверить валидность сценариев
    python nura.py assemble      6  Сборка видео из сценариев
    python nura.py all           7  Полный цикл (радар-сценарии-карусели-сборка)
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(title: str, cmd: list[str], cwd: Path | None = None) -> bool:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    r = subprocess.run(cmd, cwd=cwd or ROOT, env=_ENV)
    if r.returncode != 0:
        print(f"  x Ошибка (код {r.returncode})")
        return False
    print()
    return True


def radar() -> bool:
    return _run("1/7  Сбор трендов TikTok",
                [sys.executable, "run_radar.py"],
                cwd=ROOT / "nura-trend-radar")


def scenarios() -> bool:
    return _run("2/7  Генерация видео-сценариев (AI - JSON)",
                [sys.executable, "scripts/run_pipeline.py", "--dry-run"])


def carousels() -> bool:
    return _run("3/7  Генерация каруселей (AI - .carousel.json)",
                [sys.executable, "scripts/run_pipeline.py", "--parse-carousels"])


def xlsx() -> bool:
    return _run("4/7  Экспорт сценариев в Excel",
                [sys.executable, "scripts/run_pipeline.py", "--to-xlsx"])


def validate() -> bool:
    return _run("5/7  Валидация JSON-сценариев",
                [sys.executable, "scripts/run_pipeline.py", "--validate"])


def assemble() -> bool:
    return _run("6/7  Сборка видео",
                [sys.executable, "scripts/run_pipeline.py", "--assemble"])


def all_pipeline() -> bool:
    steps = [
        (radar, "1/7  Сбор трендов TikTok"),
        (scenarios, "2/7  AI - JSON-сценарии"),
        (carousels, "3/7  AI - карусели"),
        (xlsx, "4/7  Экспорт в Excel"),
        (validate, "5/7  Валидация"),
        (assemble, "6/7  Сборка видео"),
    ]
    for fn, title in steps:
        print(f"\n{'-' * 40}")
        print(f"  {title}")
        print(f"{'-' * 40}")
        if not fn():
            print(f"  ! Остановлено на шаге: {title}")
            return False
    print(f"\n{'=' * 60}")
    print(f"  + Полный цикл завершён")
    print(f"{'=' * 60}")
    return True


HELP = __doc__


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    mapping = {
        "radar": (radar, "радар"),
        "scenarios": (scenarios, "сценарии"),
        "carousels": (carousels, "карусели"),
        "xlsx": (xlsx, "Excel"),
        "validate": (validate, "валидация"),
        "assemble": (assemble, "сборка"),
        "all": (all_pipeline, "полный цикл"),
        "1": (radar, "радар"),
        "2": (scenarios, "сценарии"),
        "3": (carousels, "карусели"),
        "4": (xlsx, "Excel"),
        "5": (validate, "валидация"),
        "6": (assemble, "сборка"),
        "7": (all_pipeline, "полный цикл"),
        "help": ("help", "помощь"),
        "--help": ("help", "помощь"),
        "-h": ("help", "помощь"),
    }

    entry = mapping.get(cmd)
    if entry is None:
        print(f"Неизвестная команда: {cmd}\n")
        print(HELP)
        sys.exit(1)

    fn, label = entry
    if fn == "help":
        print(HELP)
        print("Короткие номера:")
        print("  python nura.py 1  - radar")
        print("  python nura.py 2  - scenarios")
        print("  python nura.py 3  - carousels")
        print("  python nura.py 4  - xlsx")
        print("  python nura.py 5  - validate")
        print("  python nura.py 6  - assemble")
        print("  python nura.py 7  - all")
        return

    sys.exit(0 if fn() else 1)


if __name__ == "__main__":
    main()
