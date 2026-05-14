import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter(prefix="/report")


@router.get("/{token}")
async def serve_report(token: str):
    html_path = f"/app/static/reports/{token}.html"
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    from jinja2 import Template

    not_found = Template("""
    <!DOCTYPE html>
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
        .box {
          padding: 40px;
        }
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
    </html>
    """)
    return HTMLResponse(content=not_found.render(), status_code=404)


@router.get("/{token}/pdf")
async def serve_report_pdf(token: str):
    pdf_path = f"/app/static/reports/{token}.pdf"
    if os.path.exists(pdf_path):
        from fastapi.responses import FileResponse

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"nura-report-{token[:8]}.pdf",
        )

    return PlainTextResponse("PDF not found", status_code=404)
