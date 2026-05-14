import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from core.database import get_async_sessionmaker
from core.repositories import ReportRepository
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
    if not os.path.exists(paths["html"]):
        return HTMLResponse(content="Report file not found", status_code=404)

    with open(paths["html"], "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/html")


@router.get("/{token}/pdf")
async def serve_report_pdf(token: str):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    report = await report_repo.get_by_token(token)

    if report is None:
        return PlainTextResponse("Report not found", status_code=404)

    paths = ReportService.get_report_path(token)
    if not os.path.exists(paths["pdf"]):
        return PlainTextResponse("PDF not found", status_code=404)

    return FileResponse(
        paths["pdf"],
        media_type="application/pdf",
        filename=f"nura-report-{token[:8]}.pdf",
    )
