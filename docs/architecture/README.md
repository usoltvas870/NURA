# NURA Architecture Documentation

**STATUS: CURRENT TECHNICAL ROUTER**

## Authority boundary

- Канонический target NURA 1.0/1.5 определяет только [product specification](../product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current implementation подтверждается code, migrations, configuration и tests; [current status](../implementation/current-status.md) служит компактным evidence-backed зеркалом.
- Этот файл только маршрутизирует к primary documents: он не является product specification или implementation proof.
- Historical и future материалы не управляют current roadmap без отдельного owner decision.

## Current architecture and technical contracts

| Domain | Primary documents |
|---|---|
| Telegram bot | [Technical specification](../bot-spec.md), [UX journey map](../bot-ux-map.md) |
| Pricing and payments | [Pricing and access map](../pricing.md), [payment flow audit](../audits/PAYMENT_FLOW_AUDIT.md) |
| Reports | [Report system specification](../report-spec.md), [structured and narrative architecture](../two-layer-architecture.md) |
| Runtime prompts | [Runtime prompt contracts](../prompt-spec.md) |
| Tarot, compatibility and referral | [Current and target map](../tarot-integration-plan.md) |
| Current implementation | [Implementation status](../implementation/current-status.md) |
| Current operations | [Admin Bot contract](../../ADMIN_BOT_SPEC.md), [deployment contract](../../DEPLOY.md) |
| Acceptance evidence | [Acceptance router](../acceptance/README.md) |
| Documentation authority | [Documentation router](../README.md) |
| Canonical product target | [NURA 1.0/1.5 product specification](../product/NURA_1_0_1_5_PRODUCT_SPEC.md) |

## Legacy, history and future

- [Legacy PWA](../archive/legacy-pwa/) — compatibility and product history, not the current roadmap.
- [Superseded documents](../archive/superseded/) — historical material, not current contracts.
- [Future vision](../vision/) — uncommitted directions.
- [Research](../research/) — non-normative inputs and dated evidence.

## Maintenance rule

- Give every new architecture document an explicit authority classification.
- Do not mix target state with implemented state.
- Do not use historical or future material as a current contract without an owner decision.
- Update this router when a primary document moves.
