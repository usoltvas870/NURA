# NURA Pricing and Access Map

**Статус документа:** CURRENT PRICING/ACCESS MAP WITH TARGET AND LEGACY BOUNDARIES
**Проверено:** 2026-07-28

## 1. Authority and purpose

Этот документ — компактная карта цен, billing paths и access semantics. Он не является product specification и не обосновывает цены маркетинговыми исследованиями.

- Target NURA 1.0/1.5, версии, цены и исключения определяет только [canonical product spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current behavior подтверждается code, migrations, config и tests; [current status](implementation/current-status.md) — компактное evidence mirror.
- Исторический payment audit и remediation boundary находятся в [Payment Flow Audit](audits/PAYMENT_FLOW_AUDIT.md).
- Старые research price points не являются current offer или committed roadmap.

## 2. Status legend

- `CURRENT — IMPLEMENTED` — путь подтверждён current code/test evidence; это не production proof.
- `TARGET — NURA 1.0` — обязательный target 1.0; не утверждение о реализации.
- `TARGET — NURA 1.5` — target 1.5; не входит в NURA 1.0.
- `IMPLEMENTATION GAP` — target contract отсутствует или неполон.
- `LEGACY COMPATIBILITY` — достижимый путь прежней monetization model, не current roadmap.
- `HISTORICAL / REMEDIATED` — прежняя модель/дефект сохранены как history, но не управляют current contract.
- `OWNER DECISION PENDING` — решение не найдено в authority sources.
- `OUT OF SCOPE` — исключено из NURA 1.0/1.5 или из этой карты.

## 3. Pricing summary

| Product/access path | Price | Billing type | Version/status | Current implementation | Notes |
|---|---:|---|---|---|---|
| Free mini-report and base functions | Бесплатно; отдельная цена не задаётся | No charge | `TARGET — NURA 1.0`; substantial `CURRENT — IMPLEMENTED` | Mini text/PDF, daily card and current free chat foundation exist | Current chat quota is 5 lifetime; target is 5 delivered answers/day |
| Full report «Матрица судьбы» | **890 ₽** | One-time purchase | `TARGET — NURA 1.0`; `CURRENT — IMPLEMENTED` locally | Dedicated `Order`/attempt/event, YooKassa, verified activation, durable full PDF/resend/refund fence | Full Telegram text and external sandbox remain gaps; no saved payment method |
| Legacy recurring subscription | **390 ₽ / 30 days** | Recurring/saved-method design | `LEGACY COMPATIBILITY` | Config, handlers, checkout, user status fields and recurring task are reachable | Not NURA 1.0, not gift, not 399 target; migration unresolved |
| Gift access after full-report purchase | No separate charge | 30 calendar days, no auto-renew | `TARGET — NURA 1.5` | Not implemented | Starts from successful purchase activation; does not require card or recurring mandate |
| Post-gift paid access | **399 ₽ / 30 days** | Separate voluntary purchase; no baseline auto-renew | `TARGET — NURA 1.5` | Not implemented | YooKassa only; an advance purchase extends current access without losing paid days; not a rename of legacy 390 path |
| Telegram Stars | — | Excluded | `OUT OF SCOPE` | Target invoice flow not found | Excluded from NURA 1.0 and 1.5 |
| Manual transfers/manual activation | — | Excluded | `OUT OF SCOPE` | Not part of dedicated checkout | Receipt screenshots/operator activation are not approved payment methods |

## 4. Current 890 ₽ purchase

`CURRENT — IMPLEMENTED` locally and `TARGET — NURA 1.0`:

- server fixes product `full_matrix`, price `89000` kopecks and currency `RUB`;
- YooKassa is the provider; `save_payment_method=false`;
- checkout persists `Order` and `PaymentAttempt` before redirect;
- browser return is informational and never proves payment, activates order, grants entitlement or triggers trusted generation;
- activation occurs only after claimed event plus server-to-server provider verification of id, paid state, amount, currency and metadata;
- trusted transaction sets attempt `succeeded`, order `paid`, confirms report payment, creates durable generation job and sets `has_matrix=True`;
- order-backed report claim, generation persistence, Telegram PDF delivery and manual resend require active `Order.status=paid`;
- refund marks order/attempt refunded, revokes `has_matrix`, fences unfinished generation and blocks new order-backed delivery/resend;
- local evidence uses fake YooKassa/Telegram; sandbox and production are not proven.

NURA 1.0 target additionally requires complete report text in Telegram alongside PDF. Current full-report delivery sends PDF/caption only, so this part remains an `IMPLEMENTATION GAP`.

## 5. Legacy 390 ₽ path

`LEGACY RECURRING 390 ₽ SUBSCRIPTION — NOT NURA 1.0 AND NOT TARGET GIFT`

Current repository evidence shows:

- `tarot_subscription_price_rub=390`;
- Telegram and PWA subscription/Tarot checkouts request `save_payment_method=true`;
- verified initial payment can activate `premium` or `tarot_subscription` for 30 days;
- active unexpired legacy entitlement bypasses current chat quota and participates in Tarot/compatibility gates;
- `User.payment_method_id`, recurring service and scheduled recurring task exist;
- expiry and local cancellation states exist.

Evidence gaps and inconsistencies:

- current wiring does not persist the returned provider `payment_method_id` into `User.payment_method_id`;
- recurring task has no dedicated payment-success contract test and, when a method is already present, extends access after provider create without separate verified-success activation;
- cancellation callback only sets `subscription_status=cancelling`; it does not call provider cancellation or remove a saved method;
- the current chat resolver treats only unexpired `premium`/Tarot states as subscriber, so `cancelling` does not retain that bypass despite legacy UI copy;
- existing subscriber count, provider mandates and production behavior were not inspected.

No conclusion is made that this path is disabled, preserved indefinitely, automatically canceled, refunded, migrated to 399 ₽ or eligible for gift access.

## 6. Target NURA 1.5 gift and 399 ₽

### Gift access

`TARGET — NURA 1.5` / `IMPLEMENTATION GAP`:

- after a successful full-report purchase activation, create one `gift_access` entitlement;
- duration: 30 calendar days;
- no card requirement, recurring mandate, automatic renewal or charge;
- purchased full report remains a separate material entitlement;
- not part of current NURA 1.0 functionality.

### Paid access after gift

`TARGET — NURA 1.5` / `IMPLEMENTATION GAP`:

- **399 ₽ for 30 days** through YooKassa;
- separate, conscious user action;
- baseline renewal is another voluntary purchase, not auto-renew;
- the next period may be bought before the current one ends and must extend access without losing already paid days;
- value includes expanded chat, approved Tarot set and other canonical 1.5 functions, not only extra messages;
- current repository has no 399 price, gift/paid entitlement aggregate, no-loss extension operation or corresponding checkout/resolver.

Automatic renewal, card storage, grace, proration and detailed future cancellation/refund mechanics must not be inferred from the legacy 390 implementation.

## 7. Entitlement matrix

| User/order state | Report access | Chat access/quota | Tarot/premium access | Billing state | Classification |
|---|---|---|---|---|---|
| Ordinary free user | Own completed mini; no order-backed full report | Universal entry; current shared quota = 5 lifetime consumed answers | Free daily card; expanded paths may show legacy gates | No active payment | `CURRENT — IMPLEMENTED`; daily quota is target gap |
| Pending 890 order/attempt | Mini only | Same as ordinary free user | No effect | Pending; browser return does not change this | `CURRENT — IMPLEMENTED` |
| Verified successful 890 purchase | Completed order-backed full PDF is listable/resendable; unfinished report proceeds through durable job | Same current free quota unless separate legacy entitlement exists | `has_matrix` alone grants no chat/premium bypass | One-time `paid` order | `CURRENT — IMPLEMENTED` locally |
| `has_matrix=True` without active paid order | Does not prove order-backed report entitlement; legacy unlinked completed reports are a separate compatibility exception | Same free quota; `has_matrix` is not chat entitlement | Surface-specific legacy code may use marker, but not canonical premium | Marker only | `CURRENT — IMPLEMENTED` boundary |
| Active paid order, generation incomplete | Purchase is durable; completed artifact not yet available | Same current chat rule | No subscription effect | Paid order; generation pending/running | `CURRENT — IMPLEMENTED` |
| Active paid order, report completed | Full PDF available in My Reports/manual resend | Same current chat rule | No subscription effect | Paid one-time order | `CURRENT — IMPLEMENTED` |
| Refunded order | Order-backed full report hidden; new resend/delivery blocked; unfinished artifact discarded | `has_matrix` revoked; no matrix-based chat effect existed | No gift/premium created | Order/attempt `refunded` | `CURRENT — IMPLEMENTED`; consumed-content policy pending |
| Active legacy premium/Tarot subscriber | Does not create a new order-backed full report | Unlimited current quota bypass while status and expiry are active | Legacy Tarot/premium gates apply by surface | Legacy 390 status; recurring code may be reachable | `LEGACY COMPATIBILITY` |
| Expired/cancelled legacy subscriber | Previously bought full report is independent; no new report entitlement | No bypass once status/expiry fails resolver | New premium/Tarot actions blocked by legacy gates | `free`, expired or `cancelling`; cancellation/provider semantics incomplete | `LEGACY COMPATIBILITY` |
| Deleted account | Reports/materials/deliveries removed; no user access | No account/chat access | No access | `Order`/`PaymentAttempt`/`PaymentEvent` retained with five-year `retain_until` metadata; `fiscal_email` remains; legacy `Payment` removed | `CURRENT — IMPLEMENTED`; cleanup/legal-copy gap |
| Gift user | Purchased report remains; target gift opens additional functions | Expanded/fair-use target access | Approved 1.5 features | No charge; 30-day entitlement | `TARGET — NURA 1.5` / `IMPLEMENTATION GAP` |
| Paid 399 user | Purchased report remains | Expanded/fair-use target access; an advance purchase extends the current term without loss of paid days | Approved 1.5 features | Separate 399 ₽ / 30-day purchase | `TARGET — NURA 1.5` / `IMPLEMENTATION GAP` |

`has_matrix → chat entitlement` is explicitly false for the current chat path. Chat bypass is derived from active legacy subscription fields; target gift/399 will require a separate canonical entitlement resolver.

## 8. Refund and access boundary

Confirmed current facts for dedicated 890 orders:

- verified full refund changes provider audit status, `PaymentAttempt` and `Order` to `refunded`;
- duplicate refund is idempotent;
- `has_matrix` becomes false;
- unfinished generation is terminalized and cannot persist or deliver a late result;
- delivery started before refund and holding the paid-order lock may complete; refund then commits after it;
- after refund, My Reports excludes the order-backed full report and new manual delivery is denied;
- a completed artifact is not automatically erased by refund itself; account deletion later removes reports/deliveries while retaining anonymized financial evidence.

The implementation does not itself define legal/product policy for partial consumption, support refund criteria or user-visible post-refund copy. Those remain outside this map unless separately approved.

`CURRENT — IMPLEMENTED`: when dedicated payment records are created, `Order`, `PaymentAttempt` and `PaymentEvent` receive `retain_until = now + 365 × 5 days`. Account deletion keeps these financial/audit rows, and the retained `PaymentAttempt` keeps `fiscal_email`. This is current technical metadata, not proof of deletion at that date or an approved legal policy: no automated cleanup/enforcement was confirmed, and the formal term/basis, further anonymization, fiscal-email handling, exceptions and user disclosure remain pending.

## 9. Owner decisions pending

- `OWNER DECISION PENDING — migration/disposition of legacy 390 ₽ subscribers and saved payment methods`: honor-to-expiry, cancellation, refunds, grandfathering, migration credit and provider-method cleanup are not approved.
- `OWNER DECISION PENDING — early-buyer gift eligibility`: eligibility date, included historical 890 purchases and gift start date are not approved.
- `OWNER DECISION PENDING — post-refund access to already delivered content`: current code blocks order-backed access/resend but product/legal policy and support copy are not approved.
- `IMPLEMENTATION GAP — future 399 ₽ lifecycle`: canonical price, 30-day term, voluntary purchase, no baseline auto-renew and no-loss advance extension are fixed; entitlement ledger/schema, expiration scheduling, atomic/idempotent extension, UI/payment activation, concurrency behavior, tests and migration are absent.
- `OWNER DECISION PENDING — future 399 ₽ details not fixed by canonical spec`: grace, proration, detailed cancellation/refund mechanics, operational reconciliation and support procedures are not approved.
- `OWNER DECISION PENDING — financial retention after account deletion`: five-year `retain_until` metadata already exists, but its formal policy/legal status, automated enforcement/cleanup, further anonymization, remaining fiscal-email handling, exceptions and user disclosure require owner/legal decision.

These decisions do not block accurate documentation of current 890 behavior. They block only legacy disposition, legal copy or future NURA 1.5 implementation.

## 10. Excluded and superseded pricing models

- Telegram Stars are excluded from NURA 1.0/1.5.
- Manual transfers, receipt screenshots and manual activation are excluded.
- The legacy 390 recurring path is not current NURA 1.0 and must not be renamed to 399 ₽.
- The target 30-day gift is not a recurring subscription and does not create a saved-card mandate.
- Historical prices such as 590 ₽, 690–990 ₽ ranges or market anchors are dated research, not current offer or roadmap.
- Compatibility/referral/Tarot pricing assumptions from older documents do not override canonical version boundaries.

## 11. References

- [Canonical target NURA 1.0/1.5](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation mirror](implementation/current-status.md)
- [Owner migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Payment flow audit](audits/PAYMENT_FLOW_AUDIT.md)
- [Telegram bot technical specification](bot-spec.md)
- [Telegram UX map](bot-ux-map.md)
- [Acceptance index](acceptance/README.md)
- [Dated current-versus-target evidence](reconciliation/2026-07-28/CURRENT_IMPLEMENTATION_VS_TARGET.md)
- [Documentation conflict matrix](reconciliation/2026-07-28/DOCUMENTATION_CONFLICT_MATRIX.md)
