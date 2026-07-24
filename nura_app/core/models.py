import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
