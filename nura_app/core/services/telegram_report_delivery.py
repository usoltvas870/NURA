"""Channel adapter orchestration for persisted mini-report results only."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.utils.formatting import escape_telegram_html, split_telegram_html_message
from core.config import settings
from core.models import MiniReportGenerationState, ReportType
from core.repositories.report import ReportRepository
from core.repositories.mini_report_generation import MiniReportGenerationRepository
from core.repositories.telegram_report_delivery import TelegramReportDeliveryRepository
from core.repositories.user import UserRepository
from core.services.report import ReportService
from core.services.telegram_sandbox import (
    RestrictedTelegramBot,
    SandboxTelegramRecipientBlocked,
    require_telegram_recipient_allowed,
)

_MINI_CONTENT_FIELDS = (
    "main_archetype",
    "core_strength",
    "emotional_conflict",
    "relationship_pattern",
    "financial_block",
)


class TelegramDeliveryError(Exception):
    def __init__(self, code: str, *, retryable: bool, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class TelegramDocument:
    message_id: int
    file_id: str | None = None
    transport: str = "artifact_upload"
    ready_message_id: int | None = None
    retry_after_seconds: int | None = None


class TelegramDocumentAdapter:
    """Small aiogram boundary; it never receives ORM or application objects."""

    async def send_message(self, chat_id: int, text: str) -> int:
        bot = await self._bot()
        try:
            message = await bot.send_message(chat_id=chat_id, text=text)
            return message.message_id
        except Exception as error:
            raise self._classify(error) from error
        finally:
            await bot.session.close()

    async def send_document(self, chat_id: int, content: bytes, filename: str, caption: str) -> TelegramDocument:
        return await self.send_document_from_artifact(chat_id, content, filename, caption)

    async def send_document_from_artifact(
        self, chat_id: int, content: bytes, filename: str, caption: str
    ) -> TelegramDocument:
        from aiogram.types import BufferedInputFile

        bot = await self._bot()
        try:
            message = await bot.send_document(chat_id=chat_id, document=BufferedInputFile(content, filename=filename), caption=caption)
            return TelegramDocument(
                message_id=message.message_id,
                file_id=getattr(getattr(message, "document", None), "file_id", None),
                transport="artifact_upload",
            )
        except Exception as error:
            raise self._classify(error) from error
        finally:
            await bot.session.close()

    async def send_document_by_file_id(
        self, chat_id: int, file_id: str, caption: str
    ) -> TelegramDocument:
        bot = await self._bot()
        try:
            message = await bot.send_document(
                chat_id=chat_id,
                document=file_id,
                caption=caption,
            )
            returned_file_id = getattr(
                getattr(message, "document", None), "file_id", None
            )
            return TelegramDocument(
                message_id=message.message_id,
                file_id=returned_file_id or file_id,
                transport="file_id",
            )
        except Exception as error:
            raise self._classify(error, file_id_transport=True) from error
        finally:
            await bot.session.close()

    @staticmethod
    async def _bot():
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        token = settings.telegram_bot_token
        if not token or token.startswith("change-me"):
            raise TelegramDeliveryError("telegram_not_configured", retryable=False)
        return RestrictedTelegramBot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    @staticmethod
    def _classify(
        error: Exception, *, file_id_transport: bool = False
    ) -> TelegramDeliveryError:
        from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

        if isinstance(error, SandboxTelegramRecipientBlocked):
            return TelegramDeliveryError(error.code, retryable=False)
        if isinstance(error, TelegramRetryAfter):
            return TelegramDeliveryError("telegram_retry_after", retryable=True, retry_after=error.retry_after)
        if isinstance(error, (TelegramNetworkError, TimeoutError)):
            return TelegramDeliveryError("telegram_network_failure", retryable=True)
        if isinstance(error, TelegramForbiddenError):
            return TelegramDeliveryError("telegram_forbidden", retryable=False)
        if isinstance(error, TelegramBadRequest):
            description = str(error).casefold()
            invalid_file_descriptions = (
                "wrong file identifier/http url specified",
                "wrong remote file identifier specified",
            )
            if file_id_transport and any(
                value in description for value in invalid_file_descriptions
            ):
                return TelegramDeliveryError("invalid_file_id", retryable=False)
            if "chat not found" in description:
                return TelegramDeliveryError(
                    "telegram_chat_not_found", retryable=False
                )
            return TelegramDeliveryError("telegram_bad_request", retryable=False)
        return TelegramDeliveryError("telegram_provider_failure", retryable=True)


class MiniReportTelegramDeliveryService:
    def __init__(self, session_factory, adapter: TelegramDocumentAdapter | None = None) -> None:
        self._reports = ReportRepository(session_factory)
        self._users = UserRepository(session_factory)
        self._generations = MiniReportGenerationRepository(session_factory)
        self._deliveries = TelegramReportDeliveryRepository(session_factory)
        self._adapter = adapter or TelegramDocumentAdapter()

    async def deliver(
        self,
        *,
        generation_id: uuid.UUID,
        user_id: uuid.UUID,
        report_id: uuid.UUID,
        purpose: str = "mini_initial",
    ) -> None:
        generation = await self._generations.get(generation_id)
        if (
            generation is None
            or generation.user_id != user_id
            or generation.report_id != report_id
            or generation.status != MiniReportGenerationState.COMPLETED
        ):
            raise TelegramDeliveryError("delivery_subject_mismatch", retryable=False)
        delivery = await self._deliveries.get_or_create(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
            purpose=purpose,
        )
        attempt = await self._deliveries.claim(delivery.id, now=datetime.now(timezone.utc))
        if attempt is None:
            return
        delivery = await self._deliveries.get(delivery.id)
        if delivery is None:
            raise TelegramDeliveryError("delivery_missing_after_claim", retryable=True)
        report = await self._reports.get_completed_mini_for_user(user_id, report_id)
        user = await self._users.get(user_id)
        if (
            report is None
            or report.report_type != ReportType.MINI.value
            or user is None
            or user.account_status != "active"
            or not user.telegram_id
        ):
            await self._deliveries.fail(
                delivery.id,
                attempt,
                "delivery_subject_missing",
                retryable=False,
            )
            raise TelegramDeliveryError("delivery_subject_missing", retryable=False)
        require_telegram_recipient_allowed(user.telegram_id)
        try:
            if delivery.text_status != "sent":
                message_ids = list(delivery.text_message_ids or [])
                chunks = self._text_chunks(report.ai_analysis or {})
                for chunk in chunks[len(message_ids):]:
                    message_ids.append(await self._adapter.send_message(user.telegram_id, chunk))
                    if not await self._deliveries.save_text_progress(delivery.id, attempt, message_ids):
                        return
                if not await self._deliveries.mark_text_sent(delivery.id, attempt, message_ids):
                    return
            if delivery.document_status != "sent":
                pdf = self._stored_mini_pdf(report)
                if pdf is None:
                    rendered_pdf = await self._mini_pdf(report)
                    stored_report = await self._reports.store_mini_pdf_if_absent(
                        report.id, user_id, rendered_pdf
                    )
                    pdf = self._stored_mini_pdf(stored_report)
                    if pdf is None:
                        raise TelegramDeliveryError(
                            "invalid_mini_pdf_artifact", retryable=False
                        )
                document = await self._adapter.send_document(user.telegram_id, pdf, "NURA-mini-report.pdf", "<b>Твой мини-разбор в PDF</b>")
                if not await self._deliveries.mark_document_sent(delivery.id, attempt, document.message_id):
                    return
            await self._deliveries.complete(delivery.id, attempt)
        except TelegramDeliveryError as error:
            await self._deliveries.fail(
                delivery.id,
                attempt,
                error.code,
                retryable=error.retryable,
            )
            raise
        except Exception as error:
            await self._deliveries.fail(
                delivery.id,
                attempt,
                "delivery_render_failure",
                retryable=True,
            )
            raise TelegramDeliveryError("delivery_render_failure", retryable=True) from error

    @staticmethod
    def _text_chunks(analysis: dict) -> list[str]:
        labels = (("Главный архетип", "main_archetype"), ("Сильная сторона", "core_strength"), ("Эмоциональный конфликт", "emotional_conflict"), ("Паттерн отношений", "relationship_pattern"), ("Денежный блок", "financial_block"))
        body = "\n\n".join(f"<b>{title}</b>\n{escape_telegram_html(analysis.get(key, ''))}" for title, key in labels)
        return split_telegram_html_message(f"<b>✨ Твой мини-разбор готов</b>\n\n{body}")

    @staticmethod
    def _stored_mini_pdf(report) -> bytes | None:
        if report is None or not isinstance(report.artifact_bytes, bytes):
            return None
        artifact = report.artifact_bytes
        if (
            report.artifact_mime_type != "application/pdf"
            or report.artifact_size_bytes != len(artifact)
            or report.artifact_sha256 != hashlib.sha256(artifact).hexdigest()
            or not artifact.startswith(b"%PDF-")
            or len(artifact) < 1024
            or len(artifact) > settings.telegram_document_max_bytes
        ):
            return None
        return artifact

    @staticmethod
    async def _mini_pdf(report) -> bytes:
        valid_content = isinstance(report.ai_analysis, dict) and all(
            isinstance(report.ai_analysis.get(field), str)
            and bool(report.ai_analysis[field])
            for field in _MINI_CONTENT_FIELDS
        )
        if (
            report.report_type != ReportType.MINI.value
            or not valid_content
            or not isinstance(report.matrix_data, dict)
        ):
            raise TelegramDeliveryError("invalid_mini_report", retryable=False)
        html = ReportService.generate_html_report({"analysis": report.ai_analysis, "matrix": report.matrix_data}, template_name="mini_report.html")
        pdf = await ReportService.generate_pdf(html)
        if not pdf.startswith(b"%PDF-") or len(pdf) < 1024:
            raise TelegramDeliveryError("invalid_mini_pdf", retryable=False)
        if len(pdf) > settings.telegram_document_max_bytes:
            raise TelegramDeliveryError("mini_pdf_oversize", retryable=False)
        return pdf
