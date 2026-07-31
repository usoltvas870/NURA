# NURA Runtime Prompt Contracts

**STATUS: CURRENT TECHNICAL ROUTER**

Текущий versioned report/chat contract, focused inventory, manifests, resolver, pinning, metadata, rollback, fallback и human-review boundary описаны в [NURA runtime prompt governance](prompt-governance.md).

Canonical product target остаётся в [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md). Runtime prompt bodies находятся только в `nura_app/core/prompts/`; этот документ и `docs/prompt-governance.md` не копируют их.

## Current classification

- `report.mini`, `report.full`, `report.kitchen`: `CURRENT — IMPLEMENTED LOCALLY`, checked-in `report/v1`.
- `chat.free`: `CURRENT — IMPLEMENTED LOCALLY`, independent checked-in `chat/v1`.
- Daily Card: separate current feature prompt path, outside report/chat defaults.
- Compatibility и expanded Tarot: legacy/1.5 feature-specific paths, isolated from new defaults; false-by-default configuration boundaries сохранены.
- External AI/provider content acceptance: `NOT EXECUTED`.
- Remote prompt CMS/editor, DB/Redis editable prompt, hot reload и A/B allocation: `OUT OF SCOPE / ABSENT`.

Implementation authority: manifests and prompt files in `nura_app/core/prompts/runtime/`, resolver in `nura_app/core/services/prompt_governance.py`, metadata-aware consumers/services, models/migration and tests. Code/tests/config имеют приоритет для implemented state.
