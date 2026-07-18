"""Generate and verify deterministic PWA release metadata without a bundler."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
RELEASE_JS = FRONTEND / "pwa" / "pwa-release.js"
RELEASE_JSON = FRONTEND / "pwa" / "pwa-release.json"
ASSETS = (
    "frontend/offline.html", "mini.html", "success.html", "frontend/pwa-install.js", "theme.css",
    "frontend/manifest.json", "frontend/pwa/app/index.html", "frontend/pwa/app/chat.html", "frontend/pwa/app/tarot.html",
    "frontend/pwa/app/profile.html", "frontend/pwa/app/success.html", "frontend/pwa/app/nura-pwa.js",
    "frontend/pwa/app/nura-pwa.css", "frontend/pwa/app/home-v9.css", "frontend/pwa/app/nura-shell-v1.css",
    "frontend/pwa/app/chat-v1-2.css", "frontend/pwa/app/tarot-v2-1.css", "frontend/pwa/app/profile-v1.css",
    "frontend/assets/vendor/vkid-sdk.js", "frontend/assets/vendor/vkid-sdk.meta.json", "frontend/assets/vendor/vkid-sdk.LICENSE",
)


def build_metadata() -> dict[str, object]:
    digests: dict[str, str] = {}
    for asset in ASSETS:
        path = ROOT / asset
        if not path.is_file():
            raise FileNotFoundError(f"required PWA asset is missing: {asset}")
        url = "/" + asset.removeprefix("frontend/")
        digests[url] = hashlib.sha256(path.read_bytes()).hexdigest()
    aggregate = hashlib.sha256(
        "".join(f"{path}:{digest}\n" for path, digest in sorted(digests.items())).encode()
    ).hexdigest()
    return {"release_id": aggregate[:16], "assets": digests}


def expected_files(metadata: dict[str, object]) -> dict[Path, str]:
    release_id = metadata["release_id"]
    return {
        RELEASE_JS: f"self.NURA_RELEASE_ID = '{release_id}';\n",
        RELEASE_JSON: json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = expected_files(build_metadata())
    stale = [path for path, content in expected.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
    if args.check:
        if stale:
            print("PWA release metadata is stale: " + ", ".join(str(path.relative_to(ROOT)) for path in stale))
            return 1
        print("PWA release metadata is current")
        return 0
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")
    print(f"Generated deterministic PWA release {build_metadata()['release_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
