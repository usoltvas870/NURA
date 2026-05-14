import asyncio
import os
import uuid

from celery import Celery

from core.config import settings
from core.models import Report
from core.services.ai import AIService
from core.services.matrix import MatrixService
from core.services.report import ReportService

celery_app = Celery("nura")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=180,
    task_soft_time_limit=150,
)

celery_app.conf.beat_schedule = {}


@celery_app.task(name="core.tasks.generate_mini_report")
def generate_mini_report(user_id: str, birth_date: str) -> dict:
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _generate_mini_report_async(user_id, birth_date)
        )
        return result
    finally:
        loop.close()


async def _generate_mini_report_async(user_id: str, birth_date: str) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    matrix = MatrixService.calculate(birth_date)
    analysis = await AIService.generate_mini_analysis(matrix)
    token = ReportService.generate_token()

    async with async_session() as session:
        report = Report(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            report_type="mini",
            token=token,
            matrix_data=matrix.model_dump(),
            ai_analysis=analysis,
        )
        session.add(report)
        await session.commit()

    await engine.dispose()
    return {"report_id": str(report.id), "token": token, "analysis": analysis}


@celery_app.task(name="core.tasks.generate_full_report")
def generate_full_report(user_id: str, birth_date: str) -> dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _generate_full_report_async(user_id, birth_date)
        )
        return result
    finally:
        loop.close()


async def _generate_full_report_async(user_id: str, birth_date: str) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    matrix = MatrixService.calculate(birth_date)
    analysis = await AIService.generate_full_report(matrix)
    token = ReportService.generate_token()

    html = ReportService.render_full(matrix.model_dump(), analysis)

    reports_dir = "/app/static/reports"
    os.makedirs(reports_dir, exist_ok=True)
    html_path = os.path.join(reports_dir, f"{token}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    pdf_path = os.path.join(reports_dir, f"{token}.pdf")
    await ReportService.generate_pdf(html, pdf_path)

    async with async_session() as session:
        report = Report(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            report_type="full",
            token=token,
            matrix_data=matrix.model_dump(),
            ai_analysis=analysis,
        )
        session.add(report)
        await session.commit()

    await engine.dispose()
    return {
        "report_id": str(report.id),
        "token": token,
        "report_url": ReportService.report_url(token),
        "analysis": analysis,
    }
