"""Channel-neutral access to persisted, completed mini reports."""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from core.repositories.mini_report_generation import MiniReportGenerationRepository
from core.repositories.report import ReportRepository
from core.repositories.telegram_report_delivery import TelegramReportDeliveryRepository
from core.repositories.user import UserRepository
from core.services.full_report_telegram_delivery import FullReportTelegramDeliveryService


PAGE_SIZE = 8


@dataclass(frozen=True)
class MyReportItem:
    report_id: uuid.UUID
    report_type: str
    created_at: datetime
    display_label: str
    supports_repeated_delivery: bool


@dataclass(frozen=True)
class MyReportsPage:
    items: tuple[MyReportItem, ...]
    page: int
    page_size: int
    total: int
    total_pages: int


@dataclass(frozen=True)
class RepeatedDeliveryRequest:
    delivery_id: uuid.UUID
    generation_id: uuid.UUID
    report_id: uuid.UUID
    purpose: str


class MyReportsService:
    """Queries report ownership in storage; callers never authorize by callback data."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._users = UserRepository(session_factory)
        self._reports = ReportRepository(session_factory)
        self._generations = MiniReportGenerationRepository(session_factory)
        self._deliveries = TelegramReportDeliveryRepository(session_factory)

    async def list_user_reports(
        self, user_id: uuid.UUID, page: int, page_size: int = PAGE_SIZE
    ) -> MyReportsPage:
        page = max(page, 0)
        page_size = min(max(page_size, 1), PAGE_SIZE)
        if not await self._is_active_user(user_id):
            return MyReportsPage((), page, page_size, 0, 0)
        reports, total = await self._reports.list_completed_mini_for_user(
            user_id, offset=page * page_size, limit=page_size
        )
        full_reports = await self._reports.list_completed_full_for_user(user_id)
        reports = sorted([*reports, *full_reports], key=lambda report: report.created_at, reverse=True)[:page_size]
        total += len(full_reports)
        return MyReportsPage(
            tuple(
                MyReportItem(
                    report_id=report.id,
                    report_type=report.report_type,
                    created_at=report.created_at,
                    display_label=f"Мини-разбор · {report.created_at.strftime('%d.%m.%Y')}",
                    supports_repeated_delivery=True,
                )
                for report in reports
            ),
            page,
            page_size,
            total,
            math.ceil(total / page_size) if total else 0,
        )

    async def get_user_report(
        self, user_id: uuid.UUID, report_id: uuid.UUID
    ) -> MyReportItem | None:
        if not await self._is_active_user(user_id):
            return None
        report = await self._reports.get_completed_mini_for_user(user_id, report_id)
        if report is None:
            report = await self._reports.get_completed_full_for_user(user_id, report_id)
        if report is None:
            return None
        return MyReportItem(
            report_id=report.id,
            report_type=report.report_type,
            created_at=report.created_at,
            display_label=f"Мини-разбор · {report.created_at.strftime('%d.%m.%Y')}",
            supports_repeated_delivery=True,
        )

    async def prepare_repeated_delivery(
        self, user_id: uuid.UUID, report_id: uuid.UUID, request_key: str
    ) -> RepeatedDeliveryRequest | None:
        if not request_key or not await self._is_active_user(user_id):
            return None
        report = await self._reports.get_completed_mini_for_user(user_id, report_id)
        if report is None:
            report = await self._reports.get_completed_full_for_user(user_id, report_id)
            if report is not None:
                delivery_id = await FullReportTelegramDeliveryService(self._session_factory).enqueue_manual(user_id, report.id, request_key)
                if delivery_id is not None:
                    return RepeatedDeliveryRequest(delivery_id, report.id, report.id, "full_manual")
        generation = await self._generations.get_completed_for_report_and_user(report_id, user_id)
        if report is None or generation is None:
            return None
        purpose = "manual_" + hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:25]
        delivery = await self._deliveries.get_or_create(
            generation_id=generation.id,
            user_id=user_id,
            report_id=report.id,
            purpose=purpose,
        )
        return RepeatedDeliveryRequest(delivery.id, generation.id, report.id, purpose)

    async def _is_active_user(self, user_id: uuid.UUID) -> bool:
        user = await self._users.get(user_id)
        return user is not None and user.account_status == "active"
