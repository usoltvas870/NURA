"""Build a sanitized, provider-free prompt governance human-review packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.services.prompt_governance import resolve_active_bundle  # noqa: E402


FIXTURES = (
    APP_ROOT
    / "tests"
    / "fixtures"
    / "prompt_review_fixtures.json"
)
CHECKLIST = (
    "factual_grounding",
    "no_invented_biography",
    "no_diagnosis",
    "no_prediction",
    "no_professional_advice",
    "no_fear_pressure",
    "nura_voice",
    "natural_rhythm",
    "specificity",
    "interpretation_is_optional",
    "schema_compliance",
)


def build_packet() -> dict[str, object]:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    report = resolve_active_bundle("report.full")
    chat = resolve_active_bundle("chat.free")
    entries: list[dict[str, object]] = []
    for fixture in fixtures["report_fixtures"]:
        entries.append(
            {
                "consumer": "report.full",
                "bundle_id": report.bundle_id,
                "bundle_version": report.bundle_version,
                "prompt_hash": report.aggregate_hash,
                "style_contract_version": report.style_contract_version,
                "output_schema_version": report.output_schema_version,
                "fixture_id": fixture["fixture_id"],
                "structured_fields": fixture["structured_fields"],
                "checklist": list(CHECKLIST),
            }
        )
    for fixture in fixtures["chat_scenarios"]:
        entries.append(
            {
                "consumer": "chat.free",
                "bundle_id": chat.bundle_id,
                "bundle_version": chat.bundle_version,
                "prompt_hash": chat.aggregate_hash,
                "style_contract_version": chat.style_contract_version,
                "fixture_id": fixture["fixture_id"],
                "scenario_category": fixture["category"],
                "checklist": list(CHECKLIST),
            }
        )
    return {
        "contract": "nura-prompt-human-review-v1",
        "external_ai_invocation": False,
        "contains_prompt_text": False,
        "contains_birth_dates": False,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a sanitized NURA prompt review packet without model calls."
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    packet = build_packet()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "entries": len(packet["entries"]),
                "external_ai_invocation": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
