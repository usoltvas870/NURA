"""Offline, read-only readiness preflight for APP_ENV=sandbox."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _emit(payload: dict[str, object]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--external-identity-check",
        choices=("telegram", "yookassa"),
        help="explicit future operator mode; no provider adapter is bundled",
    )
    args = parser.parse_args()
    os.environ["NURA_DISABLE_DOTENV"] = "1"

    if args.external_identity_check:
        _emit(
            {
                "contract": "nura-external-sandbox-preflight-v1",
                "external_network_calls": 0,
                "gates": [
                    {
                        "detail": "operator_adapter_and_separate_authorization_required",
                        "gate": f"{args.external_identity_check}_external_identity",
                        "status": "FAIL",
                    }
                ],
                "result": "BLOCKED",
            }
        )
        return 2

    try:
        from core.config import Settings
        from core.services.external_sandbox import sandbox_profile_gates
        from core.services.prompt_governance import validate_active_prompt_bundles

        current_settings = Settings()
    except Exception:
        _emit(
            {
                "contract": "nura-external-sandbox-preflight-v1",
                "external_network_calls": 0,
                "gates": [
                    {
                        "detail": "settings_load_invalid",
                        "gate": "settings_load",
                        "status": "FAIL",
                    }
                ],
                "result": "BLOCKED",
            }
        )
        return 1

    gates = list(sandbox_profile_gates(current_settings))
    try:
        validate_active_prompt_bundles()
    except Exception:
        from core.services.external_sandbox import SandboxGate

        gates.append(SandboxGate("prompt_bundles", False, "prompt_bundles_invalid"))
    else:
        from core.services.external_sandbox import SandboxGate

        gates.append(SandboxGate("prompt_bundles", True, "contract_satisfied"))

    ready = all(gate.passed for gate in gates)
    _emit(
        {
            "contract": "nura-external-sandbox-preflight-v1",
            "external_network_calls": 0,
            "gates": [gate.as_dict() for gate in gates],
            "result": "READY_FOR_EXTERNAL_IDENTITY_CHECK" if ready else "BLOCKED",
        }
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
