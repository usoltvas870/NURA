"""Build deterministic, content-addressed Major Arcana runtime assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "frontend" / "pwa" / "app" / "images"
OUTPUT_DIR = SOURCE_DIR / "major-v1"
APP_DIR = ROOT / "frontend" / "pwa" / "app"
DECK_VERSION = "major-v1"
WIDTHS = (480, 900)
COMPACT_LIMIT = 300 * 1024
FULL_LIMIT = 650 * 1024
TOTAL_LIMIT = 14 * 1024 * 1024
MIN_REDUCTION = 0.70
WEBP_PARAMETERS = {"format": "WEBP", "lossless": False, "method": 6, "quality": 80}
EXPECTED_SOURCE_HASHES = {
    "00-fool.png": "2ded1481dbcad8fdf41b1bcf5103151339d95a12d9424d213e005bf469e902ca",
    "01-magician.png": "b7c6451441a32a11f7f791e9293f6af75e69e76702eb6ad69221acc93736b80c",
    "02-high-priestess.png": "c3723a1f91aa247aa359d9745d1461c7fb66f3dfcb09b3590f2a91b79c835222",
    "03-empress.png": "902fdbc280acb79f185f13ca034e7236bf97d997d90d2e4198d06a86003211fa",
    "04-emperor.png": "99e37728979677265e4fe7f8343e108a8f8c422a61b27eac38abe209e633364d",
    "05-hierophant.png": "b9db6f2e4fde611be5597514a72aee8753b181cfb5c7c25b28ce98e9f2590880",
    "06-lovers.png": "05e7d2c1494abe5198a345217ac8a576c3370d303644415f37248ce5af298298",
    "07-chariot.png": "13d16d071d3ccfc66306b940547ce9fc59f1d8195ce74ac4b4ed899616336d85",
    "08-justice.png": "8d7eddafcb8339accf837a69724d8c3b827895666ca1158fd1f17aea7e193f5a",
    "09-hermit.png": "196bfa58b68390b7b3374418a5c4daa3811a47341e89d000f6f138a06a07ecba",
    "10-wheel-of-fortune.png": "24c70cd429d6b4a1d561036cb33ee711d4369c52aeffe1822485c9d26732e679",
    "11-strength.png": "38fe9a3392d0e9e340d835218250cf131d1acef90c6890be1a319a457a954fa9",
    "12-hanged-man.png": "300542681a3eeea45c5a1afd507ae8d320b95363df39302064d0f9522980f542",
    "13-death.png": "4adcd37ea80343a0019ce4296ef7ba0f60040a854e2690db12074a2b8c1eef84",
    "14-temperance.png": "4398fe3ae4cf727f6983400eb2ffbaa05cb457dd905fa28bab1cbd54ff701794",
    "15-devil.png": "6cc53901d70f80f1514a15071b744c478a262b7c5ace09eebfa43531e0b3419c",
    "16-tower.png": "b74d453588e875d225ae5dd25740fe3842d4816f9cccc5fa1ecb4fe5439495b7",
    "17-star.png": "d5eb0b5948c500fe4ccf3e6375ea41d8c99b91cd2e0c85a58bd2e26544298f66",
    "18-moon.png": "915eb225c63c1ebca099cbaa96660c948e4445dd4e89f1cc34a990ed215c67d6",
    "19-sun.png": "118c02ec72d2584d282fc4feddfdc5f9c2307f7a6620412c8c7849e7128eb821",
    "20-judgement.png": "eca83cec6505fa5640388a08b7378c49d58e71ba32cf26d19b3f2681cde9e99b",
    "21-world.png": "2244c95c73214cfb0036085a4fd6d0ee8d10311cb3bcd7c435b977ce88ce6e9c",
}


@dataclass(frozen=True)
class Card:
    arcana_id: int
    filename: str
    title: str
    slug: str


CARDS = (
    Card(22, "00-fool.png", "Fool", "fool"),
    Card(1, "01-magician.png", "Magician", "magician"),
    Card(2, "02-high-priestess.png", "High Priestess", "high-priestess"),
    Card(3, "03-empress.png", "Empress", "empress"),
    Card(4, "04-emperor.png", "Emperor", "emperor"),
    Card(5, "05-hierophant.png", "Hierophant", "hierophant"),
    Card(6, "06-lovers.png", "Lovers", "lovers"),
    Card(7, "07-chariot.png", "Chariot", "chariot"),
    Card(8, "08-justice.png", "Strength", "strength"),
    Card(9, "09-hermit.png", "Hermit", "hermit"),
    Card(10, "10-wheel-of-fortune.png", "Wheel of Fortune", "wheel-of-fortune"),
    Card(11, "11-strength.png", "Justice", "justice"),
    Card(12, "12-hanged-man.png", "Hanged Man", "hanged-man"),
    Card(13, "13-death.png", "Death", "death"),
    Card(14, "14-temperance.png", "Temperance", "temperance"),
    Card(15, "15-devil.png", "Devil", "devil"),
    Card(16, "16-tower.png", "Tower", "tower"),
    Card(17, "17-star.png", "Star", "star"),
    Card(18, "18-moon.png", "Moon", "moon"),
    Card(19, "19-sun.png", "Sun", "sun"),
    Card(20, "20-judgement.png", "Judgement", "judgement"),
    Card(21, "21-world.png", "World", "world"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def source_aggregate(cards: list[dict[str, Any]]) -> str:
    payload = "".join(f"{card['source_path']}:{card['source_sha256']}\n" for card in cards)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def checked_sources() -> list[dict[str, Any]]:
    expected = {card.filename for card in CARDS}
    actual = {
        path.name
        for path in SOURCE_DIR.glob("*.png")
        if path.is_file() and re.fullmatch(r"(?:0\d|1\d|2[01])-[a-z0-9-]+\.png", path.name)
    }
    if actual != expected:
        raise ValueError(f"expected exactly the approved 22 PNGs; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    result: list[dict[str, Any]] = []
    for card in CARDS:
        path = SOURCE_DIR / card.filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"source must be a regular file: {path}")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise ValueError(f"source must be RGB PNG: {path}")
            width, height = image.size
        if width != 1024 or height not in (1535, 1536):
            raise ValueError(f"unexpected source dimensions for {path}: {width}x{height}")
        digest = sha256(path)
        if digest != EXPECTED_SOURCE_HASHES[card.filename]:
            raise ValueError(f"approved source hash drift: {path}")
        result.append({
            "arcana_id": card.arcana_id,
            "filename": card.filename,
            "title": card.title,
            "slug": card.slug,
            "source_path": path.relative_to(ROOT).as_posix(),
            "source_sha256": digest,
            "source_width": width,
            "source_height": height,
            "source_bytes": path.stat().st_size,
        })
    if len({card["arcana_id"] for card in result}) != 22:
        raise ValueError("arcana IDs must be unique")
    return result


def render_derivative(source: Path, destination: Path, width: int) -> tuple[int, int, int, str]:
    with Image.open(source) as image:
        image.load()
        source_width, source_height = image.size
        target_width = min(width, source_width)
        target_height = round(source_height * target_width / source_width)
        rendered = image.convert("RGB")
        if (target_width, target_height) != rendered.size:
            rendered = rendered.resize((target_width, target_height), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        rendered.save(destination, **WEBP_PARAMETERS)
    return target_width, target_height, destination.stat().st_size, sha256(destination)


def module_bytes(cards: list[dict[str, Any]]) -> bytes:
    mapping = {
        str(card["arcana_id"]): {
            "compact": card["derivatives"]["480"]["path"],
            "full": card["derivatives"]["900"]["path"],
        }
        for card in cards
    }
    mapping_json = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (
        "/* Generated by scripts/build_tarot_assets.py; do not edit. */\n"
        "(function () {\n"
        "  'use strict';\n"
        f"  var cards = Object.freeze(Object.fromEntries(Object.entries({mapping_json}).map(function (entry) {{ return [entry[0], Object.freeze(entry[1])]; }})));\n"
        "  window.NURA = window.NURA || {};\n"
        "  window.NURA.TarotAssets = Object.freeze({\n"
        "    forArcana: function (arcanaId) { return cards[String(arcanaId)] || null; },\n"
        "    apply: function (image, asset, sizes, onError) {\n"
        "      if (!image || !asset) return false;\n"
        "      image.onerror = function () { image.onerror = null; image.removeAttribute('sizes'); image.removeAttribute('srcset'); image.removeAttribute('src'); if (typeof onError === 'function') onError(); };\n"
        "      image.decoding = 'async';\n"
        "      image.loading = 'eager';\n"
        "      image.hidden = false;\n"
        "      image.sizes = sizes;\n"
        "      image.srcset = asset.compact + ' 480w, ' + asset.full + ' 900w';\n"
        "      image.src = asset.compact;\n"
        "      return true;\n"
        "    }\n"
        "  });\n"
        "}());\n"
    ).encode("utf-8")


def build() -> dict[str, Any]:
    cards = checked_sources()
    staging = OUTPUT_DIR.with_name(f".{OUTPUT_DIR.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for card in cards:
        derivatives: dict[str, dict[str, Any]] = {}
        for width in WIDTHS:
            temporary = staging / f"{card['filename']}.{width}.webp"
            actual_width, actual_height, byte_size, digest = render_derivative(ROOT / card["source_path"], temporary, width)
            filename = f"{card['filename'][:2]}-{card['slug']}.{digest[:12]}.w{actual_width}.webp"
            final = staging / filename
            temporary.replace(final)
            derivatives[str(width)] = {
                "path": f"images/{DECK_VERSION}/{filename}",
                "sha256": digest,
                "width": actual_width,
                "height": actual_height,
                "bytes": byte_size,
            }
        card["derivatives"] = derivatives
    manifest = {
        "schema": 1,
        "deck": DECK_VERSION,
        "source_set_sha256": source_aggregate(cards),
        "generator": {"pillow": Image.__version__, "webp": {"method": 6, "quality": 80, "lossless": False}, "widths": list(WIDTHS)},
        "cards": cards,
    }
    manifest_bytes = canonical_json(manifest)
    manifest_name = f"tarot-assets.{hashlib.sha256(manifest_bytes).hexdigest()[:12]}.json"
    (staging / manifest_name).write_bytes(manifest_bytes)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    staging.replace(OUTPUT_DIR)
    for stale in APP_DIR.glob("tarot-assets-v1.*.js"):
        stale.unlink()
    module = module_bytes(cards)
    module_path = APP_DIR / f"tarot-assets-v1.{hashlib.sha256(module).hexdigest()[:12]}.js"
    module_path.write_bytes(module)
    return manifest


def expected_manifest() -> tuple[Path, dict[str, Any]]:
    manifests = sorted(OUTPUT_DIR.glob("tarot-assets.*.json"))
    if len(manifests) != 1:
        raise ValueError("expected exactly one content-addressed Tarot manifest")
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, manifest


def validate_size_gates(card: dict[str, Any], derivative: dict[str, Any], width: int) -> None:
    limit = COMPACT_LIMIT if width == 480 else FULL_LIMIT
    if not 0 < derivative["bytes"] < card["source_bytes"] or derivative["bytes"] > limit:
        raise ValueError(f"size gate failed: {derivative['path']}")
    if derivative["width"] > card["source_width"] or derivative["height"] > card["source_height"]:
        raise ValueError(f"upscale gate failed: {derivative['path']}")


def check() -> None:
    sources = checked_sources()
    manifest_path, manifest = expected_manifest()
    output_entries = list(OUTPUT_DIR.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in output_entries):
        raise ValueError("Tarot output directory must contain regular files only")
    expected_paths = {derivative["path"].rsplit("/", 1)[-1] for card in manifest.get("cards", []) for derivative in card.get("derivatives", {}).values()}
    expected_paths.add(manifest_path.name)
    if len(expected_paths) != 45 or {path.name for path in output_entries} != expected_paths:
        raise ValueError("Tarot output inventory drift")
    if canonical_json(manifest) != manifest_path.read_bytes() or not manifest_path.name.endswith(f"{sha256(manifest_path)[:12]}.json"):
        raise ValueError("manifest is not canonical or content-addressed")
    if manifest.get("source_set_sha256") != source_aggregate(sources):
        raise ValueError("source aggregate hash drift")
    manifest_sources = [{key: value for key, value in card.items() if key != "derivatives"} for card in manifest.get("cards", [])]
    if manifest_sources != sources:
        raise ValueError("manifest source metadata drift")
    with tempfile.TemporaryDirectory(prefix="nura-tarot-verify-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        for card in manifest["cards"]:
            source_path = ROOT / card["source_path"]
            for width in WIDTHS:
                derivative = card["derivatives"][str(width)]
                temporary = temporary_root / f"{card['filename']}.{width}.webp"
                actual_width, actual_height, byte_size, digest = render_derivative(source_path, temporary, width)
                expected_name = f"{card['filename'][:2]}-{card['slug']}.{digest[:12]}.w{actual_width}.webp"
                if (actual_width, actual_height, byte_size, digest) != (
                    derivative["width"], derivative["height"], derivative["bytes"], derivative["sha256"],
                ) or derivative["path"] != f"images/{DECK_VERSION}/{expected_name}":
                    raise ValueError(f"non-deterministic derivative drift: {source_path}")
                validate_size_gates(card, derivative, width)
    for card in manifest["cards"]:
        for derivative in card["derivatives"].values():
            path = ROOT / "frontend" / "pwa" / "app" / derivative["path"]
            if not path.is_file() or sha256(path) != derivative["sha256"] or path.stat().st_size != derivative["bytes"]:
                raise ValueError(f"derivative drift: {path}")
            with Image.open(path) as image:
                if image.format != "WEBP" or image.size != (derivative["width"], derivative["height"]):
                    raise ValueError(f"invalid WebP derivative: {path}")
    total_source = sum(card["source_bytes"] for card in manifest["cards"])
    total_derivatives = sum(derivative["bytes"] for card in manifest["cards"] for derivative in card["derivatives"].values())
    if total_derivatives > TOTAL_LIMIT or total_derivatives > total_source * (1 - MIN_REDUCTION):
        raise ValueError("Tarot derivative total size gate failed")
    modules = sorted(APP_DIR.glob("tarot-assets-v1.*.js"))
    if len(modules) != 1:
        raise ValueError("expected exactly one content-addressed Tarot mapping module")
    expected_module = module_bytes(manifest["cards"])
    if modules[0].read_bytes() != expected_module or modules[0].name != f"tarot-assets-v1.{hashlib.sha256(expected_module).hexdigest()[:12]}.js":
        raise ValueError("Tarot mapping module drift")


def write_baseline(directory: Path) -> None:
    cards = checked_sources()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source-inventory.json").write_bytes(canonical_json({"cards": cards, "source_set_sha256": source_aggregate(cards)}))
    (directory / "source-hashes.txt").write_text("".join(f"{card['source_sha256']}  {card['source_path']}\n" for card in cards), encoding="utf-8")
    (directory / "runtime-reference-map.md").write_text("# Runtime reference map\n\nHome, Tarot, and Chat each resolve one selected card after their existing payload path. No page preloads the deck.\n", encoding="utf-8")
    (directory / "network-baseline.md").write_text("# Network baseline\n\nGuest paths request zero Tarot faces; authenticated Home, Tarot, and Chat each resolve at most one selected face.\n", encoding="utf-8")
    (directory / "sizing-decision.md").write_text("# Sizing decision\n\nThe approved runtime derivatives are 480px compact and 900px high-density WebP variants. Both preserve source aspect ratio and never upscale.\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--baseline-dir", type=Path)
    args = parser.parse_args()
    if args.baseline_dir:
        write_baseline(args.baseline_dir)
    if args.command == "build":
        build()
        print("Built deterministic Tarot WebP assets")
    else:
        check()
        print("Tarot assets are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
