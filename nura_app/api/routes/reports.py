import os
import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from core.database import get_async_sessionmaker
from core.repositories import ReportRepository, UserRepository
from core.services.matrix import ARCANA, MatrixService
from core.services.report import ReportService

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


@router.get("/{token}")
async def serve_report(token: str):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    report = await report_repo.get_by_token(token)

    if report is None:
        return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)

    paths = ReportService.get_report_path(token)
    if os.path.exists(paths["html"]):
        with open(paths["html"], "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/html")

    html = await _render_report_html(report, session_factory)
    if html is None:
        return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)
    return Response(content=html, media_type="text/html")


@router.get("/{token}/pdf")
async def serve_report_pdf(token: str):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    report = await report_repo.get_by_token(token)

    if report is None:
        return PlainTextResponse("Report not found", status_code=404)

    paths = ReportService.get_report_path(token)
    if os.path.exists(paths["pdf"]):
        return FileResponse(
            paths["pdf"],
            media_type="application/pdf",
            filename=f"nura-report-{token[:8]}.pdf",
        )

    html = await _render_report_html(report, session_factory)
    if html is None:
        return PlainTextResponse("Report not found", status_code=404)
    from weasyprint import HTML as WPHTML
    pdf_bytes = WPHTML(string=html).write_pdf()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=nura-report-{token[:8]}.pdf"})


async def _render_report_html(report, session_factory):
    matrix_data = report.matrix_data or {}
    analysis = report.ai_analysis or {}
    user_id = matrix_data.get("user_id") or str(report.user_id)

    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    user_repo = UserRepository(session_factory)
    user = await user_repo.get(uid)

    if not user:
        user_name = "пользователь"
        archetype_name = ARCANA.get(matrix_data.get("center", 0), {}).get("name", "Неизвестный")
        archetype_number = matrix_data.get("center", 0)
    else:
        user_name = user.first_name or user.username or "пользователь"
        archetype_number = user.main_archetype_number or matrix_data.get("center", 0)
        archetype_name = user.main_archetype or ARCANA.get(archetype_number, {}).get("name", "Неизвестный")

    recommendations_parsed = ReportService.parse_recommendations(
        analysis.get("ai_recommendations", "")
    )

    matrix_raw = {
        "center": matrix_data.get("center"),
        "top": matrix_data.get("top"),
        "bottom": matrix_data.get("bottom"),
        "left": matrix_data.get("left"),
        "right": matrix_data.get("right"),
        "talent_zone": matrix_data.get("talent_zone"),
        "comfort_zone": matrix_data.get("comfort_zone"),
        "portrait_zone": matrix_data.get("portrait_zone"),
        "karmic_tail": matrix_data.get("karmic_tail"),
        "sky_line": matrix_data.get("sky_line"),
        "earth_line": matrix_data.get("earth_line"),
        "relationship_line": matrix_data.get("relationship_line"),
        "money_line": matrix_data.get("money_line"),
        "relationship_point": matrix_data.get("relationship_point"),
        "arcana_names": matrix_data.get("arcana_names", {}),
    }

    report_data = {
        "matrix": matrix_raw,
        "analysis": analysis,
        "user_name": user_name,
        "archetype_name": archetype_name,
        "archetype_number": archetype_number,
        "recommendations_parsed": recommendations_parsed,
    }

    return ReportService.generate_html_report(report_data)
