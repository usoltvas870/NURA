"""Deterministic synthetic fixtures for the P5B backup/restore proof."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg2.extras import Json

FIXTURE_SET = "p5b-v1"
FIXED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

USER_PRIMARY = UUID("10000000-0000-0000-0000-000000000001")
USER_REFERRED = UUID("10000000-0000-0000-0000-000000000002")
GUEST_PRIMARY = UUID("20000000-0000-0000-0000-000000000001")
PROMO_PRIMARY = UUID("30000000-0000-0000-0000-000000000001")
PAYMENT_PRIMARY = UUID("40000000-0000-0000-0000-000000000001")
PAYMENT_SECONDARY = UUID("40000000-0000-0000-0000-000000000002")
REPORT_PRIMARY = UUID("50000000-0000-0000-0000-000000000001")
REPORT_SECONDARY = UUID("50000000-0000-0000-0000-000000000002")
JOB_PRIMARY = UUID("60000000-0000-0000-0000-000000000001")
JOB_SECONDARY = UUID("60000000-0000-0000-0000-000000000002")
RESERVATION_PRIMARY = UUID("70000000-0000-0000-0000-000000000001")

EXPECTED_ROW_COUNTS = {
    "attribution_links": 0,
    "attribution_touches": 0,
    "broadcast_audit_entries": 0,
    "broadcast_campaigns": 0,
    "broadcast_cta_clicks": 0,
    "broadcast_cta_click_events": 0,
    "broadcast_deliveries": 0,
    "chat_message_usages": 0,
    "daily_tarot_draws": 0,
    "full_report_telegram_deliveries": 0,
    "guest_profiles": 1,
    "mini_report_generations": 0,
    "orders": 0,
    "payment_attempts": 0,
    "payment_events": 0,
    "payments": 2,
    "promo_codes": 1,
    "promo_reservations": 1,
    "referral_rewards": 1,
    "report_generation_jobs": 2,
    "reports": 2,
    "telegram_report_deliveries": 0,
    "telegram_suppressions": 0,
    "users": 2,
}


def _execute(cursor: Any, statement: str, parameters: tuple[object, ...]) -> None:
    adapted = tuple(
        str(value)
        if isinstance(value, UUID)
        else Json(value)
        if isinstance(value, (dict, list))
        else value
        for value in parameters
    )
    cursor.execute(statement, adapted)


def insert_synthetic_fixtures(connection: Any) -> None:
    """Insert the complete deterministic fixture graph using parameterized SQL."""
    with connection.cursor() as cursor:
        _execute(
            cursor,
            """
            INSERT INTO users (
                id, telegram_id, name, email, username, first_name, birth_date,
                main_archetype, main_archetype_number, subscription_status,
                subscription_until, payment_method_id, tarot_subscription,
                tarot_subscription_until, has_matrix, compatibility_used,
                referred_by, has_pwa_push, notification_prefs, pd_consent_at,
                auth_method, email_verified, phone_verified, vk_id, created_at,
                last_activity_at, account_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                USER_PRIMARY,
                900000000000000001,
                "Synthetic Aurora",
                "fixture.one@example.invalid",
                "synthetic_user_one",
                "Синтетика",
                "2000-01-01",
                "synthetic_archetype",
                7,
                "active_fixture",
                FIXED_AT,
                "synthetic_method_001",
                True,
                FIXED_AT,
                True,
                False,
                900000000000000099,
                False,
                {"ritual": "synthetic", "unicode": "проверка"},
                FIXED_AT,
                "synthetic_email",
                True,
                False,
                "synthetic_vk_001",
                FIXED_AT,
                FIXED_AT,
                "active",
            ),
        )
        _execute(
            cursor,
            """
            INSERT INTO users (
                id, telegram_id, name, birth_date, subscription_status,
                tarot_subscription, has_matrix, compatibility_used, has_pwa_push,
                email_verified, phone_verified, created_at, account_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                USER_REFERRED,
                900000000000000002,
                "Synthetic Nullable",
                "2001-02-03",
                "free",
                False,
                False,
                True,
                False,
                False,
                False,
                FIXED_AT,
                "active",
            ),
        )
        _execute(
            cursor,
            """
            INSERT INTO guest_profiles (
                id, guest_token, name, birth_date, quiz_answers, report_data,
                created_at, expires_at, merged_to_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                GUEST_PRIMARY,
                "synthetic_guest_001",
                "Synthetic Guest",
                "1999-09-09",
                {"answers": [1, None, "синтетика"]},
                {"result": "synthetic_result"},
                FIXED_AT,
                datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
                USER_PRIMARY,
            ),
        )
        _execute(
            cursor,
            """
            INSERT INTO promo_codes (
                id, code, discount_percent, max_uses, used_count,
                reserved_count, expires_at, is_active, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                PROMO_PRIMARY,
                "SYNTHETIC25",
                25,
                10,
                1,
                1,
                datetime(2026, 12, 31, 23, 59, tzinfo=UTC),
                True,
                FIXED_AT,
            ),
        )
        for values in (
            (
                PAYMENT_PRIMARY,
                USER_PRIMARY,
                890,
                89000,
                "succeeded",
                "synthetic_payment_001",
                "matrix",
                PROMO_PRIMARY,
                FIXED_AT,
                FIXED_AT,
                FIXED_AT,
            ),
            (
                PAYMENT_SECONDARY,
                USER_REFERRED,
                390,
                None,
                "pending",
                "synthetic_payment_002",
                "subscription",
                None,
                None,
                None,
                FIXED_AT,
            ),
        ):
            _execute(
                cursor,
                """
                INSERT INTO payments (
                    id, user_id, amount, amount_kopecks, status, yookassa_id,
                    payment_type, promo_code_id, promo_consumed_at,
                    promo_reserved_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                values,
            )
        for values in (
            (
                REPORT_PRIMARY,
                USER_PRIMARY,
                "full",
                "synthetic_report_001",
                {"matrix": [1, 2, 3], "nullable": None},
                {"analysis": "синтетический текст"},
                {"kitchen": True},
                FIXED_AT,
                datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
                PAYMENT_PRIMARY,
                "payment_confirmed",
                FIXED_AT,
                "completed",
                FIXED_AT,
                FIXED_AT,
                FIXED_AT,
                None,
                1,
                None,
            ),
            (
                REPORT_SECONDARY,
                USER_REFERRED,
                "mini",
                "synthetic_report_002",
                None,
                None,
                None,
                FIXED_AT,
                None,
                None,
                "awaiting_payment",
                None,
                "not_requested",
                None,
                None,
                None,
                None,
                0,
                None,
            ),
        ):
            _execute(
                cursor,
                """
                INSERT INTO reports (
                    id, user_id, report_type, token, matrix_data, ai_analysis,
                    kitchen_analysis, created_at, expires_at, payment_id,
                    payment_state, payment_confirmed_at, generation_state,
                    generation_enqueued_at, generation_started_at, generated_at,
                    generation_failed_at, generation_attempts,
                    generation_error_category
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                values,
            )
        for values in (
            (
                JOB_PRIMARY,
                REPORT_PRIMARY,
                "full_report",
                "completed",
                1,
                None,
                FIXED_AT,
                FIXED_AT,
                FIXED_AT,
                None,
                None,
                "synthetic_task_001",
                FIXED_AT,
                FIXED_AT,
            ),
            (
                JOB_SECONDARY,
                REPORT_SECONDARY,
                "full_report",
                "pending_dispatch",
                0,
                FIXED_AT,
                None,
                None,
                None,
                None,
                None,
                None,
                FIXED_AT,
                FIXED_AT,
            ),
        ):
            _execute(
                cursor,
                """
                INSERT INTO report_generation_jobs (
                    id, report_id, job_type, state, attempts, next_attempt_at,
                    claimed_at, published_at, completed_at, failed_at,
                    last_error_category, celery_task_id, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                values,
            )
        _execute(
            cursor,
            """
            INSERT INTO referral_rewards (
                id, referrer_id, referred_id, event, rewarded_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (7, USER_PRIMARY, USER_REFERRED, "synthetic_referral", FIXED_AT),
        )
        _execute(
            cursor,
            """
            INSERT INTO promo_reservations (
                id, promo_code_id, user_id, payment_type, final_amount_kopecks,
                currency, idempotency_key, report_token, state, expires_at,
                provider_payment_id, payment_id, consumed_at, released_at,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                RESERVATION_PRIMARY,
                PROMO_PRIMARY,
                USER_PRIMARY,
                "matrix",
                66750,
                "RUB",
                "synthetic_idempotency_001",
                "synthetic_report_001",
                "consumed",
                datetime(2026, 1, 15, 12, 30, tzinfo=UTC),
                "synthetic_provider_001",
                PAYMENT_SECONDARY,
                FIXED_AT,
                None,
                FIXED_AT,
            ),
        )
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)",
            ("referral_rewards", "id", 41),
        )
    connection.commit()


def fixture_manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        "fixture_set": FIXTURE_SET,
        "fixed_timestamp": FIXED_AT.isoformat().replace("+00:00", "Z"),
        "expected_row_counts": EXPECTED_ROW_COUNTS,
        "reserved_email_domain": "example.invalid",
        "synthetic_payment_prefix": "synthetic_",
        "sequence_floor": {"referral_rewards_id_seq": 41},
    }
    payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {**manifest, "manifest_sha256": hashlib.sha256(payload).hexdigest()}
