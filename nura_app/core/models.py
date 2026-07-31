import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_SHA256_HEX_CHECK = "length(artifact_sha256) = 64 AND " + " AND ".join(
    f"substr(artifact_sha256, {position}, 1) IN "
    "('0','1','2','3','4','5','6','7','8','9','a','b','c','d','e','f')"
    for position in range(1, 65)
)


class Base(DeclarativeBase):
    pass


class ReportType(str, enum.Enum):
    MINI = "mini"
    FULL = "full"
    COMPATIBILITY = "compatibility"


class ReportPaymentState:
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_CONFIRMED = "payment_confirmed"
    LEGACY_UNLINKED = "legacy_unlinked"


class OrderStatus:
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class ReportGenerationState:
    NOT_REQUESTED = "not_requested"
    PENDING_DISPATCH = "pending_dispatch"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class ReportGenerationJobState:
    PENDING_DISPATCH = "pending_dispatch"
    DISPATCHING = "dispatching"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class MiniReportGenerationState:
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class DailyTarotDrawState:
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class TelegramReportDeliveryState:
    PENDING = "pending"
    DELIVERING = "delivering"
    PARTIALLY_DELIVERED = "partially_delivered"
    DELIVERED = "delivered"
    FAILED = "failed"


class FullReportTelegramDeliveryState:
    QUEUED = "queued"
    SENDING = "sending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class BroadcastCampaignState:
    DRAFT = "draft"
    TESTED = "tested"
    QUEUED = "queued"
    SENDING = "sending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


class BroadcastDeliveryState:
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    BLOCKED = "blocked"
    SUPPRESSED_OPT_OUT = "suppressed_opt_out"
    SUPPRESSED_FREQUENCY = "suppressed_frequency"
    CANCELED = "canceled"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("name", "birth_date", name="uq_user_name_birth_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    web_session_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    main_archetype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    main_archetype_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_status: Mapped[str] = mapped_column(
        String(20), default="free", nullable=False, server_default="free"
    )
    subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_method_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    tarot_subscription: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    tarot_subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    has_matrix: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    compatibility_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    referred_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    has_pwa_push: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    push_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_p256dh: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_auth: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_prefs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    editorial_messages_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    web_session_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pd_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    auth_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    vk_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    account_status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, server_default="active"
    )


class DailyTarotDraw(Base):
    """One durable, user-local daily Tarot result."""

    __tablename__ = "daily_tarot_draws"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_daily_tarot_draws_user_local_date"),
        CheckConstraint(
            "status IN ('pending', 'generating', 'completed', 'failed')",
            name="ck_daily_tarot_draws_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_daily_tarot_draws_attempt_count"),
        CheckConstraint(
            "arcana_number IS NULL OR arcana_number BETWEEN 1 AND 22",
            name="ck_daily_tarot_draws_arcana_number",
        ),
        CheckConstraint(
            "(status = 'pending' AND interpretation IS NULL AND claimed_at IS NULL "
            "AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL "
            "AND error_detail IS NULL AND attempt_count = 0) OR "
            "(status = 'generating' AND arcana_number IS NOT NULL "
            "AND interpretation IS NULL AND claimed_at IS NOT NULL "
            "AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL "
            "AND error_detail IS NULL AND attempt_count >= 1) OR "
            "(status = 'completed' AND arcana_number IS NOT NULL "
            "AND interpretation IS NOT NULL AND length(trim(interpretation)) > 0 "
            "AND claimed_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failed_at IS NULL AND error_code IS NULL AND error_detail IS NULL "
            "AND attempt_count >= 1) OR "
            "(status = 'failed' AND arcana_number IS NOT NULL "
            "AND interpretation IS NULL AND claimed_at IS NOT NULL "
            "AND completed_at IS NULL AND failed_at IS NOT NULL "
            "AND error_code IS NOT NULL AND attempt_count >= 1)",
            name="ck_daily_tarot_draws_state",
        ),
        Index("ix_daily_tarot_draws_user_local_date", "user_id", "local_date"),
        Index("ix_daily_tarot_draws_status_claimed_at", "status", "claimed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DailyTarotDrawState.PENDING
    )
    arcana_number: Mapped[int | None] = mapped_column(Integer)
    interpretation: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChatMessageUsage(Base):
    """Durable reservation ledger for the shared free-chat allowance."""

    __tablename__ = "chat_message_usages"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_chat_message_usages_user_request"),
        CheckConstraint(
            "channel IN ('telegram', 'web')", name="ck_chat_message_usages_channel"
        ),
        CheckConstraint(
            "status IN ('reserved', 'result_ready', 'consumed', 'released')",
            name="ck_chat_message_usages_status",
        ),
        CheckConstraint(
            "(status IN ('reserved', 'released') AND response_text IS NULL) OR "
            "(status IN ('result_ready', 'consumed') AND response_text IS NOT NULL)",
            name="ck_chat_message_usages_response_state",
        ),
        CheckConstraint(
            "(status = 'reserved' AND consumed_at IS NULL AND released_at IS NULL AND result_ready_at IS NULL) OR "
            "(status = 'result_ready' AND consumed_at IS NULL AND released_at IS NULL AND result_ready_at IS NOT NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND released_at IS NULL AND result_ready_at IS NOT NULL) OR "
            "(status = 'released' AND consumed_at IS NULL AND released_at IS NOT NULL AND result_ready_at IS NULL)",
            name="ck_chat_message_usages_timestamps_state",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'queued', 'sending', 'retryable', 'delivered', 'awaiting_ack', 'failed')",
            name="ck_chat_message_usages_delivery_status",
        ),
        CheckConstraint("delivery_attempt_count >= 0", name="ck_chat_message_usages_delivery_attempt_count"),
        Index("ix_chat_message_usages_user_status", "user_id", "status"),
        Index("ix_chat_message_usages_stale_reserved", "status", "reserved_at"),
        Index("ix_chat_message_usages_delivery_claim", "delivery_status", "delivery_claimed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="reserved")
    billable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    delivery_total_chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_next_chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivery_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivery_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    delivery_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_chat_id_snapshot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AttributionLink(Base):
    __tablename__ = "attribution_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    campaign: Mapped[str] = mapped_column(String(128), nullable=False)
    content_id: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AttributionTouch(Base):
    __tablename__ = "attribution_touches"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_code", name="uq_attribution_touches_user_code"),
        Index("ix_attribution_touches_user_id", "user_id"),
        Index("ix_attribution_touches_link_id", "attribution_link_id"),
        Index("ix_attribution_touches_first_seen_at", "first_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    attribution_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attribution_links.id"), nullable=True
    )
    raw_start_parameter: Mapped[str] = mapped_column(String(66), nullable=False)
    normalized_code: Mapped[str] = mapped_column(String(24), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    visit_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )


class GuestProfile(Base):
    __tablename__ = "guest_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    guest_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quiz_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    merged_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_reports_payment_id"),
        Index("ix_reports_payment_id", "payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(
        String(20),
        default=ReportType.MINI.value,
        nullable=False,
        server_default=ReportType.MINI.value,
    )
    token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    matrix_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    kitchen_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True, unique=True, index=True,
    )
    payment_state: Mapped[str] = mapped_column(
        String(32),
        default=ReportPaymentState.AWAITING_PAYMENT,
        server_default=ReportPaymentState.AWAITING_PAYMENT,
        nullable=False,
    )
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_state: Mapped[str] = mapped_column(
        String(32),
        default=ReportGenerationState.NOT_REQUESTED,
        server_default=ReportGenerationState.NOT_REQUESTED,
        nullable=False,
    )
    generation_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    generation_error_category: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    artifact_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportGenerationJob(Base):
    __tablename__ = "report_generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "job_type", name="uq_report_generation_jobs_report_job_type"
        ),
        Index(
            "ix_report_generation_jobs_state_next_attempt_created",
            "state",
            "next_attempt_at",
            "created_at",
        ),
        Index("ix_report_generation_jobs_report_id", "report_id"),
        Index("ix_report_generation_jobs_celery_task_id", "celery_task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(
        String(32), default="full_report", server_default="full_report", nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32),
        default=ReportGenerationJobState.PENDING_DISPATCH,
        server_default=ReportGenerationJobState.PENDING_DISPATCH,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MiniReportGeneration(Base):
    """Durable idempotency and lifecycle record for a channel-neutral mini report."""

    __tablename__ = "mini_report_generations"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND guest_profile_id IS NULL) OR "
            "(user_id IS NULL AND guest_profile_id IS NOT NULL)",
            name="ck_mini_report_generations_exactly_one_owner",
        ),
        Index(
            "uq_mini_report_generations_user_fingerprint_version",
            "user_id",
            "fingerprint",
            "generation_version",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_mini_report_generations_guest_fingerprint_version",
            "guest_profile_id",
            "fingerprint",
            "generation_version",
            unique=True,
            postgresql_where=text("guest_profile_id IS NOT NULL"),
            sqlite_where=text("guest_profile_id IS NOT NULL"),
        ),
        Index("ix_mini_report_generations_status", "status"),
        Index("ix_mini_report_generations_report_id", "report_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guest_profiles.id", ondelete="CASCADE"),
        nullable=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default=MiniReportGenerationState.PENDING,
        server_default=MiniReportGenerationState.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    generation_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TelegramReportDelivery(Base):
    """Durable progress for the initial Telegram delivery of a mini report."""

    __tablename__ = "telegram_report_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "mini_report_generation_id", "user_id", "purpose",
            name="uq_telegram_report_deliveries_generation_user_purpose",
        ),
        CheckConstraint(
            "status IN ('pending', 'delivering', 'partially_delivered', 'delivered', 'failed')",
            name="ck_telegram_report_deliveries_status",
        ),
        CheckConstraint(
            "text_status IN ('pending', 'sent')",
            name="ck_telegram_report_deliveries_text_status",
        ),
        CheckConstraint(
            "document_status IN ('pending', 'sent')",
            name="ck_telegram_report_deliveries_document_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_report_deliveries_attempt_count",
        ),
        Index("ix_telegram_report_deliveries_status", "status"),
        Index(
            "ix_telegram_report_deliveries_status_claimed_at",
            "status",
            "claimed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    mini_report_generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mini_report_generations.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, server_default="mini_initial")
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=TelegramReportDeliveryState.PENDING)
    text_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    document_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_message_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    document_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class FullReportTelegramDelivery(Base):
    """Durable full-report text and PDF delivery; independent from mini-report lifecycle."""

    __tablename__ = "full_report_telegram_deliveries"
    __table_args__ = (
        UniqueConstraint("report_id", "delivery_reason", "request_key", name="uq_full_report_delivery_request"),
        CheckConstraint("delivery_reason IN ('automatic', 'manual')", name="ck_full_report_delivery_reason"),
        CheckConstraint("status IN ('queued', 'sending', 'completed', 'failed', 'canceled')", name="ck_full_report_delivery_status"),
        CheckConstraint("text_status IN ('pending', 'sent', 'legacy_not_delivered')", name="ck_full_report_delivery_text_status"),
        CheckConstraint("document_status IN ('pending', 'sent')", name="ck_full_report_delivery_document_status"),
        CheckConstraint("attempt_count >= 0", name="ck_full_report_delivery_attempt_count"),
        CheckConstraint("artifact_size_bytes > 0", name="ck_full_report_delivery_artifact_size"),
        CheckConstraint(
            _SHA256_HEX_CHECK,
            name="ck_full_report_delivery_artifact_sha256",
        ),
        CheckConstraint(
            "(status = 'queued' AND claimed_at IS NULL AND sent_at IS NULL AND failed_at IS NULL) OR "
            "(status = 'sending' AND claimed_at IS NOT NULL AND attempt_count > 0 AND sent_at IS NULL AND failed_at IS NULL) OR "
            "(status = 'completed' AND claimed_at IS NULL AND sent_at IS NOT NULL AND failed_at IS NULL "
            "AND telegram_document_message_id IS NOT NULL AND document_status = 'sent' AND retryable = false "
            "AND (text_status = 'sent' OR delivery_format_version = 'pdf-only-v0')) OR "
            "(status = 'failed' AND claimed_at IS NULL AND failed_at IS NOT NULL AND sent_at IS NULL "
            "AND error_code IS NOT NULL) OR "
            "(status = 'canceled' AND claimed_at IS NULL AND sent_at IS NULL AND retryable = false)",
            name="ck_full_report_delivery_state",
        ),
        Index(
            "uq_full_report_delivery_automatic_report",
            "report_id",
            unique=True,
            postgresql_where=text("delivery_reason = 'automatic'"),
            sqlite_where=text("delivery_reason = 'automatic'"),
        ),
        Index("ix_full_report_delivery_report_id", "report_id"),
        Index("ix_full_report_delivery_order_id", "order_id"),
        Index("ix_full_report_delivery_user_id", "user_id"),
        Index("ix_full_report_delivery_status_claimed_at", "status", "claimed_at"),
        Index("ix_full_report_delivery_queued_at", "queued_at"),
        Index("ix_full_report_delivery_request_key", "request_key"),
        Index(
            "uq_full_report_delivery_active_report",
            "report_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'sending') OR "
                "(status = 'failed' AND retryable = true)"
            ),
            sqlite_where=text(
                "status IN ('queued', 'sending') OR "
                "(status = 'failed' AND retryable = true)"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    delivery_reason: Mapped[str] = mapped_column(String(16), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=FullReportTelegramDeliveryState.QUEUED)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_chat_id_snapshot: Mapped[int | None] = mapped_column(BigInteger)
    delivery_format_version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="full-text-pdf-v1"
    )
    text_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    text_chunks_snapshot: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    total_text_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    text_message_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    text_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="pending"
    )
    document_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    telegram_document_message_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_caption_message_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256))
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_kopecks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )
    yookassa_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    payment_type: Mapped[str] = mapped_column(
        String(20), default="subscription", nullable=False
    )
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id"), nullable=True, index=True
    )
    promo_consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promo_reserved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Order(Base):
    """Canonical one-time full Matrix order, retained after account deletion."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_kopecks > 0", name="ck_orders_amount_positive"),
        CheckConstraint("currency = 'RUB'", name="ck_orders_currency_rub"),
        CheckConstraint("product_code = 'full_matrix'", name="ck_orders_product_full_matrix"),
        CheckConstraint("status IN ('created', 'pending', 'paid', 'failed', 'canceled', 'refunded')", name="ck_orders_status"),
        CheckConstraint("(status IN ('paid', 'refunded')) = (paid_at IS NOT NULL)", name="ck_orders_paid_at_status"),
        CheckConstraint("(status = 'refunded') = (refunded_at IS NOT NULL)", name="ck_orders_refunded_at_status"),
        CheckConstraint("(status = 'canceled') = (canceled_at IS NOT NULL)", name="ck_orders_canceled_at_status"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_pending", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    checkout_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    checkout_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    telegram_id_snapshot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False, server_default="full_matrix")
    amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="89000")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="RUB")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=OrderStatus.CREATED)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="SET NULL", use_alter=True, name="fk_orders_report"),
        unique=True,
        nullable=True,
    )
    active_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="SET NULL", use_alter=True, name="fk_orders_active_payment"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payment_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(256))
    customer_reference_hash: Mapped[str | None] = mapped_column(String(128))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    anonymization_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payment_attempts_provider_id"),
        CheckConstraint("amount_kopecks > 0", name="ck_payment_attempts_amount_positive"),
        CheckConstraint("currency = 'RUB'", name="ck_payment_attempts_currency_rub"),
        CheckConstraint("status IN ('pending', 'succeeded', 'canceled', 'refunded', 'failed')", name="ck_payment_attempts_status"),
        CheckConstraint("(status IN ('succeeded', 'refunded')) = (paid_at IS NOT NULL)", name="ck_payment_attempts_paid_at_status"),
        CheckConstraint("(status = 'refunded') = (refunded_at IS NOT NULL)", name="ck_payment_attempts_refunded_at_status"),
        CheckConstraint("(status = 'canceled') = (canceled_at IS NOT NULL)", name="ck_payment_attempts_canceled_at_status"),
        Index("ix_payment_attempts_order_status", "order_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, server_default="yookassa")
    provider_payment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="RUB")
    confirmation_url: Mapped[str | None] = mapped_column(Text)
    fiscal_email: Mapped[str | None] = mapped_column(String(320))
    cancellation_code: Mapped[str | None] = mapped_column(String(64))
    cancellation_party: Mapped[str | None] = mapped_column(String(32))
    provider_metadata: Mapped[dict | None] = mapped_column(JSONB)
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    customer_reference_hash: Mapped[str | None] = mapped_column(String(128))
    anonymization_reason: Mapped[str | None] = mapped_column(String(64))


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_payment_events_dedup_key"),
        CheckConstraint("provider = 'yookassa'", name="ck_payment_events_provider"),
        CheckConstraint("processing_status IN ('received', 'processing', 'processed', 'failed')", name="ck_payment_events_processing_status"),
        CheckConstraint("attempt_count >= 0", name="ck_payment_events_attempt_count"),
        CheckConstraint("processing_status != 'processed' OR processed_at IS NOT NULL", name="ck_payment_events_processed_at"),
        CheckConstraint("processing_status != 'failed' OR (failed_at IS NOT NULL AND error_code IS NOT NULL)", name="ck_payment_events_failed_at"),
        CheckConstraint("processing_status != 'processed' OR retryable = false", name="ck_payment_events_processed_not_retryable"),
        CheckConstraint("processing_status NOT IN ('received', 'processing') OR (processed_at IS NULL AND failed_at IS NULL)", name="ck_payment_events_nonterminal_timestamps"),
        Index("ix_payment_events_attempt_created", "payment_attempt_id", "created_at"),
        Index("ix_payment_events_provider_object", "provider", "provider_object_id", "provider_event_type"),
        Index("ix_payment_events_provider_payment", "provider_payment_id"),
        Index("ix_payment_events_status_claim", "processing_status", "claimed_at"),
        Index("ix_payment_events_order", "order_id"),
        Index("ix_payment_events_received", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, server_default="yookassa")
    provider_event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"))
    payment_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payment_attempts.id", ondelete="RESTRICT"))
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="received")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(256))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anonymization_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    referred_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    rewarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromoReservation(Base):
    __tablename__ = "promo_reservations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("promo_codes.id"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    payment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    final_amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    report_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="reserved", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"), unique=True, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaigns"
    __table_args__ = (
        CheckConstraint("campaign_type IN ('editorial', 'commercial')", name="ck_broadcast_campaigns_type"),
        CheckConstraint(
            "status IN ('draft', 'tested', 'queued', 'sending', 'completed', 'canceled', 'failed')",
            name="ck_broadcast_campaigns_status",
        ),
        CheckConstraint("content_version >= 1", name="ck_broadcast_campaigns_version"),
        CheckConstraint("attribution_window_days BETWEEN 1 AND 30", name="ck_broadcast_campaigns_attribution_window"),
        CheckConstraint("selected_count >= 0 AND delivered_count >= 0 AND blocked_count >= 0 AND suppressed_count >= 0 AND failed_count >= 0", name="ck_broadcast_campaigns_counts"),
        Index("ix_broadcast_campaigns_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    campaign_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(16))
    media_file_id: Mapped[str | None] = mapped_column(String(256))
    cta_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    segment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    segment_parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    attribution_window_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)
    launched_by: Mapped[str | None] = mapped_column(String(64))
    tested_version: Mapped[int | None] = mapped_column(Integer)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_message_ids: Mapped[list | None] = mapped_column(JSONB)
    preview_version: Mapped[int | None] = mapped_column(Integer)
    preview_count: Mapped[int | None] = mapped_column(Integer)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    launch_idempotency_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_broadcast_deliveries_campaign_user"),
        CheckConstraint(
            "status IN ('queued', 'sending', 'delivered', 'failed_retryable', 'failed_terminal', 'blocked', 'suppressed_opt_out', 'suppressed_frequency', 'canceled')",
            name="ck_broadcast_deliveries_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_broadcast_deliveries_attempts"),
        Index("ix_broadcast_deliveries_campaign_status", "campaign_id", "status", "created_at"),
        Index("ix_broadcast_deliveries_user_delivered", "user_id", "delivered_at"),
        Index("ix_broadcast_deliveries_retry", "status", "retry_not_before", "claimed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_chat_id_snapshot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    click_token: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_message_id: Mapped[int | None] = mapped_column(BigInteger)
    text_message_id: Mapped[int | None] = mapped_column(BigInteger)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BroadcastCTAClick(Base):
    __tablename__ = "broadcast_cta_clicks"
    __table_args__ = (
        UniqueConstraint("delivery_id", "cta_key", name="uq_broadcast_cta_clicks_delivery_key"),
        CheckConstraint("click_count BETWEEN 1 AND 1000000", name="ck_broadcast_cta_clicks_count"),
        Index("ix_broadcast_cta_clicks_campaign_clicked", "campaign_id", "last_clicked_at"),
        Index("ix_broadcast_cta_clicks_user_clicked", "user_id", "last_clicked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False)
    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_deliveries.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cta_key: Mapped[str] = mapped_column(String(16), nullable=False)
    destination: Mapped[str] = mapped_column(String(32), nullable=False)
    first_clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class BroadcastCTAClickEvent(Base):
    __tablename__ = "broadcast_cta_click_events"
    __table_args__ = (
        Index("ix_broadcast_cta_click_events_campaign_clicked", "campaign_id", "clicked_at"),
        Index("ix_broadcast_cta_click_events_user_clicked", "user_id", "clicked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    click_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_cta_clicks.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False)
    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_deliveries.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cta_key: Mapped[str] = mapped_column(String(16), nullable=False)
    destination: Mapped[str] = mapped_column(String(32), nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attribution_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramSuppression(Base):
    __tablename__ = "telegram_suppressions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_telegram_suppressions_user"),
        CheckConstraint("reason IN ('bot_blocked', 'chat_not_found', 'operator')", name="ck_telegram_suppressions_reason"),
        Index("ix_telegram_suppressions_active", "active", "reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastAuditEntry(Base):
    __tablename__ = "broadcast_audit_entries"
    __table_args__ = (Index("ix_broadcast_audit_campaign_created", "campaign_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256))
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
