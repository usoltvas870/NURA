import logging
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from core.database import get_async_sessionmaker
from core.services.report import ReportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report")

NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NURA — Отчёт</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: #0a0a0a;
      color: #e0e0e0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
    }
    .box { padding: 40px; }
    h1 { font-size: 24px; color: #2d8a56; font-weight: 300; letter-spacing: 4px; margin-bottom: 16px; }
    p { color: #5a5a5a; font-size: 14px; }
  </style>
</head>
<body>
  <div class="box">
    <h1>N U R A</h1>
    <p>Отчёт не найден или ещё готовится.<br>Пожалуйста, вернитесь в бот и запросите отчёт заново.</p>
  </div>
</body>
</html>"""

GENERATING_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NURA — Отчёт готовится</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: #0a0a0a;
      color: #e0e0e0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
    }
    .box { padding: 40px; max-width: 480px; }
    h1 { font-size: 24px; color: #C9A55C; font-weight: 300; letter-spacing: 4px; margin-bottom: 20px; }
    p { color: #8a8a8a; font-size: 15px; line-height: 1.6; margin-bottom: 10px; }
    .pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #C9A55C; margin-right: 8px; animation: pulse 1.5s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
  </style>
</head>
<body>
  <div class="box">
    <h1>N U R A</h1>
    <p><span class="pulse"></span>Отчёт ещё готовится</p>
    <p>NURA анализирует твою матрицу. Обычно это занимает 1–2 минуты. Обнови страницу или вернись позже.</p>
  </div>
</body>
</html>"""


@router.get("/{token}")
async def serve_report(token: str):
    session_factory = get_async_sessionmaker()
    report = await ReportService.get_report_by_token(session_factory, token)

    if report is None:
        return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)

    paths = ReportService.get_report_path(token)
    if os.path.exists(paths["html"]):
        with open(paths["html"], "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/html")

    html = await _render_report_by_type(report, session_factory)
    if html is None:
        return HTMLResponse(content=GENERATING_HTML, status_code=202)
    return Response(content=html, media_type="text/html")


@router.get("/{token}/pdf")
async def serve_report_pdf(token: str):
    session_factory = get_async_sessionmaker()
    report = await ReportService.get_report_by_token(session_factory, token)

    if report is None:
        return PlainTextResponse("Report not found", status_code=404)

    paths = ReportService.get_report_path(token)
    if os.path.exists(paths["pdf"]):
        return FileResponse(
            paths["pdf"],
            media_type="application/pdf",
            filename=f"nura-report-{token[:8]}.pdf",
        )

    html = await _render_report_by_type(report, session_factory)
    if html is None:
        return PlainTextResponse("Report is still generating. Please try again later.", status_code=202)
    import sys
    sys.setrecursionlimit(5000)
    from weasyprint import HTML as WPHTML
    try:
        pdf_bytes = WPHTML(string=html).write_pdf()
    except RecursionError:
        return PlainTextResponse("PDF generation failed: CSS complexity too high. Please try again later.", status_code=500)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=nura-report-{token[:8]}.pdf"})


async def _render_report_by_type(report, session_factory) -> str | None:
    from core.models import ReportType

    report_type = getattr(report, "report_type", None)
    if isinstance(report_type, str):
        report_type = report_type.lower()

    if report_type == ReportType.MINI.value:
        return await ReportService.render_report_html(report, session_factory, template_name="mini_report.html")

    if report_type == ReportType.FULL.value:
        analysis = getattr(report, "ai_analysis", None) or {}
        if ReportService._is_fallback_analysis(analysis):
            return None
        return await ReportService.render_report_html(report, session_factory)

    if report_type == ReportType.COMPATIBILITY.value:
        return await ReportService.render_report_html(report, session_factory, template_name="compatibility_report.html")

    logger.warning("Unknown report_type=%s for token=%s, falling back to old renderer",
                   report_type, getattr(report, "token", "unknown"))
    return await ReportService.render_report_html(report, session_factory)


@router.get("/{token}/kitchen")
async def serve_kitchen_analysis(token: str):
    session_factory = get_async_sessionmaker()
    report = await ReportService.get_report_by_token(session_factory, token)

    if report is None or report.kitchen_analysis is None:
        return PlainTextResponse("Kitchen analysis not found", status_code=404)

    return report.kitchen_analysis
