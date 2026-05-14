import os
import uuid

from jinja2 import Template

from core.config import settings

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "frontend",
    "reports",
)


MINI_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NURA — Мини-разбор</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: #0a0a0a;
      color: #e0e0e0;
      line-height: 1.6;
    }
    .container { max-width: 680px; margin: 0 auto; padding: 32px 20px; }
    .logo { text-align: center; margin-bottom: 40px; }
    .logo h1 {
      font-size: 28px;
      color: #2d8a56;
      font-weight: 300;
      letter-spacing: 4px;
    }
    .card {
      background: #141414;
      border: 1px solid #1e1e1e;
      border-radius: 12px;
      padding: 28px;
      margin-bottom: 20px;
    }
    .card h2 {
      font-size: 18px;
      color: #2d8a56;
      margin-bottom: 12px;
      font-weight: 400;
    }
    .card p { font-size: 15px; color: #b0b0b0; }
    .archetype {
      text-align: center;
      padding: 40px 20px;
    }
    .archetype .label {
      font-size: 13px;
      color: #5a5a5a;
      text-transform: uppercase;
      letter-spacing: 3px;
      margin-bottom: 8px;
    }
    .archetype .name {
      font-size: 36px;
      color: #f0a050;
      font-weight: 300;
    }
    .matrix-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      max-width: 300px;
      margin: 40px auto;
    }
    .matrix-cell {
      aspect-ratio: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #141414;
      border: 1px solid #1e1e1e;
      border-radius: 8px;
      font-size: 14px;
      color: #5a5a5a;
    }
    .matrix-cell.center {
      border-color: #2d8a56;
      color: #f0a050;
      font-size: 20px;
      font-weight: 300;
    }
    .cta {
      margin-top: 40px;
      text-align: center;
    }
    .cta-button {
      display: inline-block;
      background: linear-gradient(135deg, #2d8a56, #1a5c38);
      color: #fff;
      padding: 16px 40px;
      border-radius: 8px;
      text-decoration: none;
      font-size: 16px;
      font-weight: 400;
      transition: opacity 0.2s;
    }
    .cta-button:hover { opacity: 0.9; }
    .footer {
      text-align: center;
      margin-top: 60px;
      font-size: 12px;
      color: #2a2a2a;
    }
  </style>
</head>
<body>
<div class="container">
  <div class="logo"><h1>N U R A</h1></div>

  <div class="archetype">
    <div class="label">Главный архетип</div>
    <div class="name">{{ analysis.main_archetype }}</div>
  </div>

  <div class="matrix-grid">
    <div class="matrix-cell">{{ matrix.top }}</div>
    <div class="matrix-cell">{{ matrix.talent_zone }}</div>
    <div class="matrix-cell">{{ matrix.right }}</div>
    <div class="matrix-cell">{{ matrix.comfort_zone }}</div>
    <div class="matrix-cell center">{{ matrix.center }}</div>
    <div class="matrix-cell">{{ matrix.portrait_zone }}</div>
    <div class="matrix-cell">{{ matrix.left }}</div>
    <div class="matrix-cell">{{ matrix.portrait_zone }}</div>
    <div class="matrix-cell">{{ matrix.bottom }}</div>
  </div>

  <div class="card">
    <h2>Сильная сторона</h2>
    <p>{{ analysis.core_strength }}</p>
  </div>

  <div class="card">
    <h2>Эмоциональный конфликт</h2>
    <p>{{ analysis.emotional_conflict }}</p>
  </div>

  <div class="card">
    <h2>Паттерн отношений</h2>
    <p>{{ analysis.relationship_pattern }}</p>
  </div>

  <div class="card">
    <h2>Денежный блок</h2>
    <p>{{ analysis.financial_block }}</p>
  </div>

  <div class="cta">
    <a href="https://t.me/{{ bot_username }}" class="cta-button">
      Получить полный AI-разбор за 590 ₽
    </a>
  </div>

  <div class="footer">NURA · AI-проводник в Матрицу Судьбы</div>
</div>
</body>
</html>"""

FULL_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NURA — Полный AI-отчёт</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: #0a0a0a;
      color: #e0e0e0;
      line-height: 1.7;
    }
    .container { max-width: 720px; margin: 0 auto; padding: 40px 20px; }
    .hero {
      text-align: center;
      padding: 60px 0 40px;
      border-bottom: 1px solid #1e1e1e;
      margin-bottom: 40px;
    }
    .hero h1 {
      font-size: 32px;
      color: #2d8a56;
      font-weight: 300;
      letter-spacing: 6px;
      margin-bottom: 16px;
    }
    .hero .archetype {
      font-size: 42px;
      color: #f0a050;
      font-weight: 300;
    }
    .hero .date {
      font-size: 13px;
      color: #3a3a3a;
      margin-top: 8px;
      letter-spacing: 2px;
    }
    .section {
      margin-bottom: 32px;
      padding-bottom: 32px;
      border-bottom: 1px solid #141414;
    }
    .section h2 {
      font-size: 20px;
      color: #2d8a56;
      margin-bottom: 14px;
      font-weight: 400;
    }
    .section p { font-size: 15px; color: #b0b0b0; }
    .matrix-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      max-width: 320px;
      margin: 40px auto;
    }
    .matrix-cell {
      aspect-ratio: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: #141414;
      border: 1px solid #1e1e1e;
      border-radius: 8px;
      font-size: 12px;
    }
    .matrix-cell .num { font-size: 20px; color: #f0a050; font-weight: 300; }
    .matrix-cell .label { font-size: 10px; color: #3a3a3a; margin-top: 4px; }
    .matrix-cell.center {
      border-color: #2d8a56;
    }
    .matrix-cell.center .num { font-size: 28px; }
    .footer {
      text-align: center;
      margin-top: 60px;
      font-size: 12px;
      color: #1a1a1a;
    }
  </style>
</head>
<body>
<div class="container">
  <div class="hero">
    <h1>N U R A</h1>
    <div class="archetype">{{ analysis.main_archetype }}</div>
    <div class="date">{{ matrix.birth_date }}</div>
  </div>

  <div class="section">
    <h2>Сильные стороны</h2>
    <p>{{ analysis.strengths }}</p>
  </div>

  <div class="section">
    <h2>Теневая сторона</h2>
    <p>{{ analysis.shadow_side }}</p>
  </div>

  <div class="section">
    <h2>Динамика отношений</h2>
    <p>{{ analysis.relationship_dynamics }}</p>
  </div>

  <div class="section">
    <h2>Финансовый сценарий</h2>
    <p>{{ analysis.financial_scenario }}</p>
  </div>

  <div class="section">
    <h2>Повторяющиеся ошибки</h2>
    <p>{{ analysis.recurring_mistakes }}</p>
  </div>

  <div class="section">
    <h2>Внутренние конфликты</h2>
    <p>{{ analysis.internal_conflicts }}</p>
  </div>

  <div class="section">
    <h2>Жизненные циклы</h2>
    <p>{{ analysis.life_cycles }}</p>
  </div>

  <div class="section">
    <h2>Персональные рекомендации</h2>
    <p>{{ analysis.ai_recommendations }}</p>
  </div>

  <div class="footer">NURA · AI-проводник в Матрицу Судьбы · {{ matrix.birth_date }}</div>
</div>
</body>
</html>"""


class ReportService:
    @staticmethod
    def render_mini(matrix: dict, analysis: dict, bot_username: str = "nura_ai_bot") -> str:
        tmpl = Template(MINI_TEMPLATE)
        return tmpl.render(matrix=matrix, analysis=analysis, bot_username=bot_username)

    @staticmethod
    def render_full(matrix: dict, analysis: dict) -> str:
        tmpl = Template(FULL_TEMPLATE)
        return tmpl.render(matrix=matrix, analysis=analysis)

    @staticmethod
    async def generate_pdf(html: str, output_path: str) -> str:
        from weasyprint import HTML

        HTML(string=html).write_pdf(output_path)
        return output_path

    @staticmethod
    def generate_token() -> str:
        return uuid.uuid4().hex[:32]

    @staticmethod
    def report_url(token: str) -> str:
        return f"{settings.report_base_url}/report/{token}"
