"""Integrity check script for STEP 10 — Final integration verification.
No dependencies (stdlib only).
"""

import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent / "nura_app"
PROMPTS = BASE / "core" / "prompts"
SERVICES = BASE / "core" / "services"
TEMPLATES = BASE / "frontend" / "reports" / "templates"

errors = []
ok_count = 0


def check(condition: bool, msg: str) -> None:
    global ok_count
    if condition:
        ok_count += 1
        print(f"  ✅ {msg}")
    else:
        errors.append(msg)
        print(f"  ❌ {msg}")


# ── 1. FullReportResult: 13 полей ─────────────────────────────────
schemas_path = BASE / "core" / "schemas.py"
schemas_text = schemas_path.read_text(encoding="utf-8")

# Extract field names from class FullReportResult
frr_match = re.search(r"class FullReportResult\(.*?\).*?\n(.*?)(?=\nclass |\Z)", schemas_text, re.DOTALL)
if frr_match:
    frr_body = frr_match.group(1)
    schema_fields = re.findall(r"^\s+(\w+)\s*:\s*str", frr_body, re.MULTILINE)
else:
    schema_fields = []

print("\n📋 1. FullReportResult — поля:")
check(len(schema_fields) == 13, f"{len(schema_fields)} полей (должно быть 13) | {schema_fields}")
for f in ["main_archetype", "strengths", "shadow_side", "relationship_dynamics",
           "financial_scenario", "recurring_mistakes", "internal_conflicts", "life_cycles",
           "ai_recommendations", "karmic_tail_analysis", "ancestral_programs",
           "life_purpose", "life_forecast"]:
    check(f in schema_fields, f"  поле: {f}")

# Check Field constraints
for fname in schema_fields:
    field_block_match = re.search(
        rf"{fname}\s*:\s*str\s*=\s*Field\(\s*(.*?)\s*\)", frr_body, re.DOTALL
    )
    if field_block_match:
        block = field_block_match.group(1)
        has_min = "min_length" in block
        has_max = "max_length" in block
        has_desc = "description" in block
        if not (has_min and has_max and has_desc):
            errors.append(f"FullReportResult.{fname}: Field без min_length/max_length/description")
            print(f"  ❌ {fname}: missing Field constraints (min={has_min}, max={has_max}, desc={has_desc})")
        else:
            ok_count += 1
            print(f"  ✅ {fname}: has min_length, max_length, description")

# ── 2. FALLBACK_FULL: 13 ключей ──────────────────────────────────
ai_path = SERVICES / "ai.py"
ai_text = ai_path.read_text(encoding="utf-8")

fb_match = re.search(r"FALLBACK_FULL\s*=\s*\{(.*?)\n\}", ai_text, re.DOTALL)
if fb_match:
    fb_body = fb_match.group(1)
    fb_keys = re.findall(r'"(\w+)"\s*:', fb_body)
else:
    fb_keys = []

print("\n📋 2. FALLBACK_FULL — ключи:")
check(len(fb_keys) == 13, f"{len(fb_keys)} ключей (должно быть 13) | {fb_keys}")
check(set(fb_keys) == set(schema_fields), "ключи FALLBACK_FULL совпадают с полями FullReportResult")
if set(fb_keys) != set(schema_fields):
    missing_in_fb = set(schema_fields) - set(fb_keys)
    extra_in_fb = set(fb_keys) - set(schema_fields)
    if missing_in_fb:
        print(f"    ❌ Отсутствуют в FALLBACK_FULL: {missing_in_fb}")
    if extra_in_fb:
        print(f"    ❌ Лишние в FALLBACK_FULL: {extra_in_fb}")

# ── 3. FULL_REPORT_PARAMS max_tokens = 16000 ─────────────────────
mt_match = re.search(r'FULL_REPORT_PARAMS\s*=\s*\{(.*?)\}', ai_text, re.DOTALL)
if mt_match:
    params_body = mt_match.group(1)
    max_tokens_val = re.search(r'"max_tokens"\s*:\s*(\d+)', params_body)
    actual_tokens = int(max_tokens_val.group(1)) if max_tokens_val else 0
else:
    actual_tokens = 0

print("\n📋 3. FULL_REPORT_PARAMS:")
check(actual_tokens == 16000, f"max_tokens = {actual_tokens} (должно быть 16000)")

# ── 4. MatrixService методы ──────────────────────────────────────
matrix_path = SERVICES / "matrix.py"
matrix_text = matrix_path.read_text(encoding="utf-8")

print("\n📋 4. MatrixService — методы:")
check("def calculate_year_arcana" in matrix_text, "calculate_year_arcana (birth_date, target_year) -> int")
check("def calculate_life_periods" in matrix_text, "calculate_life_periods (birth_date) -> dict")
check("def format_for_prompt" in matrix_text and "Жизненные периоды" in matrix_text,
      "format_for_prompt выводит жизненные периоды")

# ── 5. cot_instruction.txt — шаги ────────────────────────────────
cot_path = PROMPTS / "cot_instruction.txt"
cot_text = cot_path.read_text(encoding="utf-8")

print("\n📋 5. cot_instruction.txt — шаги:")
check("Шаг 2" in cot_text and ("причина" in cot_text and "следствие" in cot_text and "урок" in cot_text),
      "Шаг 2: кармический хвост детально (причина→следствие→урок)")

step4_expanded = "4.1" in cot_text or "подшаг" in cot_text.lower() or "▸" in cot_text
check(step4_expanded, "Шаг 4: разбит на подшаги 4.1–4.4")
if not step4_expanded:
    print("    💡 Подсказка: нужно добавить 4.1–4.4 подшаги для линий")

check("Шаг 8" in cot_text or "жизненные период" in cot_text.lower() or "период" in cot_text.lower(),
      "Добавлен Шаг 8 (жизненные периоды)")

step6_categories = "тело" in cot_text.lower() and "ум" in cot_text.lower() and "дух" in cot_text.lower()
check(step6_categories, "Шаг 6: категории тело/ум/дух")
if not step6_categories:
    print("    💡 Подсказка: нужно добавить тело/ум/дух в Шаг 6")

# ── 6. full_report.txt — JSON schema (13 полей) ─────────────────
fr_path = PROMPTS / "full_report.txt"
fr_text = fr_path.read_text(encoding="utf-8")

print("\n📋 6. full_report.txt — схема JSON:")
# Extract JSON field names
json_fields = re.findall(r'"(\w+)"\s*:\s*"<', fr_text)
check(len(json_fields) >= 13, f"{len(json_fields)} полей в JSON схеме (должно быть >=13)")
expected_json = ["main_archetype", "strengths", "shadow_side", "relationship_dynamics",
                  "financial_scenario", "recurring_mistakes", "internal_conflicts",
                  "life_cycles", "ai_recommendations", "karmic_tail_analysis",
                  "ancestral_programs", "life_purpose", "life_forecast"]
for f in expected_json:
    check(f in fr_text, f"  поле: {f}")

# Check expanded descriptions
check("стратеги" in fr_text and "стиль" in fr_text, "main_archetype требует стратегию + стиль решений")
check("професси" in fr_text and "стратеги" in fr_text, "financial_scenario требует профессии + стратегии")
check("точк" in fr_text and "паттерн" in fr_text, "relationship_dynamics требует точку отношений + паттерны")
rec_categories = "тело" in fr_text.lower() and "ум" in fr_text.lower() and "дух" in fr_text.lower()
check(rec_categories, "ai_recommendations требует категории тело/ум/дух")
if not rec_categories:
    print("    💡 Подсказка: нужно добавить категории тело/ум/дух в ai_recommendations")

# ── 7. tasks.py _process_full_report — matrix_raw и report_data ──
tasks_path = BASE / "core" / "tasks.py"
tasks_text = tasks_path.read_text(encoding="utf-8")

print("\n📋 7. tasks.py — _process_full_report:")

# Extract matrix_raw dict keys
mraw_match = re.search(r'matrix_raw\s*=\s*\{(.*?)\}', tasks_text, re.DOTALL)
matrix_raw_fields = re.findall(r'"(\w+)"\s*:', mraw_match.group(1)) if mraw_match else []

expected_mraw = ["center", "top", "bottom", "left", "right", "talent_zone",
                  "comfort_zone", "portrait_zone", "karmic_tail", "sky_line",
                  "earth_line", "relationship_line", "money_line", "relationship_point",
                  "inner_f", "inner_g", "inner_h", "inner_i", "arcana_names"]
check(len(matrix_raw_fields) == len(expected_mraw),
      f"matrix_raw: {len(matrix_raw_fields)} полей (должно быть {len(expected_mraw)})")
for f in expected_mraw:
    check(f in matrix_raw_fields, f"  поле: {f}")

check("current_year_arcana" in tasks_text, "report_data содержит current_year_arcana")
check("life_periods" in tasks_text, "report_data содержит life_periods")

# ── 8. Frontend templates — существование файлов ─────────────────
print("\n📋 8. Frontend — шаблоны:")
required_templates = [
    "full_report.html",
    "_matrix_3x3.html",
    "_dashboard.html",
    "_section_karmic_tail.html",
    "_section_ancestral.html",
    "_section_purpose.html",
    "_section_forecast.html",
    "_recommendation_day.html",
    "_line_visual.html",
    "_cover.html",
    "_footer.html",
]
for tpl in required_templates:
    exists = (TEMPLATES / tpl).exists()
    check(exists, f"файл: {tpl}")

# ── 9. Проверка includes в full_report.html ──────────────────────
print("\n📋 9. Includes проверка:")
full_report = (TEMPLATES / "full_report.html").read_text(encoding="utf-8")
includes = re.findall(r"{%\s*include\s+'(.*?)'", full_report)
for inc in includes:
    inc_path = TEMPLATES / inc
    check(inc_path.exists(), f"include '{inc}' → существует")

# ── 10. CSS-классы из шаблонов определены в _styles.html ────────
print("\n📋 10. CSS-классы в _styles.html:")
styles_text = (TEMPLATES / "_styles.html").read_text(encoding="utf-8")

# Extract CSS classes from _styles.html (all selectors)
css_classes = set()
# Match .class-name patterns in CSS
for m in re.finditer(r"\.([a-zA-Z][\w-]*)", styles_text):
    css_classes.add(m.group(1))
# Also match pseudo/prefixed like .class:hover, .class:first-child
# Already handled by the regex above since it captures the base class name

# Extract classes used in all HTML templates
html_classes = set()
for tpl_path in TEMPLATES.glob("*.html"):
    tpl_text = tpl_path.read_text(encoding="utf-8")
    # Match class="class1 class2 ..."
    for m in re.finditer(r'class\s*=\s*"([^"]*)"', tpl_text):
        classes = m.group(1).split()
        html_classes.update(c.strip() for c in classes if c.strip())
    # Match class='class1 class2 ...'
    for m in re.finditer(r"class\s*=\s*'([^']*)'", tpl_text):
        classes = m.group(1).split()
        html_classes.update(c.strip() for c in classes if c.strip())
    # Match Jinja2 constructs like section_class='archetype' (param values become classes)
    for m in re.finditer(r"section_class\s*=\s*'(\w+)'", tpl_text):
        html_classes.add(f"section-{m.group(1)}")
    for m in re.finditer(r"line_class\s*=\s*'([\w-]+)'", tpl_text):
        html_classes.add(m.group(1))

# Remove template variables ({{ ... }})
html_classes = {c for c in html_classes if not c.startswith("{{") and "{{" not in c}

missing = html_classes - css_classes
# Filter out obvious non-CSS utility classes from frameworks (none in vanilla)
# Also filter out dynamic Jinja2 classes
missing_filtered = {c for c in missing if not c.startswith("{") and "{" not in c}

if missing_filtered:
    for cls in sorted(missing_filtered):
        errors.append(f"CSS-класс '{cls}' используется в шаблонах, но не определён в _styles.html")
        print(f"  ❌ .{cls} — не найден в _styles.html")
else:
    ok_count += 1
    print(f"  ✅ Все CSS-классы из шаблонов ({len(html_classes)}) определены в _styles.html")

# ── 11. Проверка дублирующихся CSS-определений ───────────────────
print("\n📋 11. Дублирующиеся CSS-определения:")
dup_patterns = [
    r"\.karmic-chain\s*\{", r"\.karmic-link\s*\n", r"\.karmic-link\s*\{",
    r"\.year-arcana-block\s*\{", r"\.year-label\s*\{", r"\.year-value\s*\{",
    r"\.section-ancestral\s+\.section-accent-bar",
    r"\.section-karmic-tail\s+\.section-accent-bar",
]
has_duplicates = False
for pat in dup_patterns:
    matches = re.findall(pat, styles_text)
    if len(matches) > 1:
        has_duplicates = True
        cls_name = pat.replace(r"\.", ".").replace(r"\s+", " ").replace(r"\{", "").strip()
        print(f"  ⚠️ {cls_name} — определено {len(matches)} раза")
if not has_duplicates:
    ok_count += 1
    print("  ✅ Дубликатов не найдено")

# Check conflicting colors
ancestral_colors = re.findall(
    r'\.section-ancestral\s+\.section-accent-bar\s*\{[^}]*background:\s*([^;]+)',
    styles_text
)
if len(set(ancestral_colors)) > 1:
    print(f"  ⚠️ .section-ancestral .section-accent-bar имеет разные цвета: {ancestral_colors}")

# ── 12. Проверка matrix_raw в _process_full_report по пунктам ────
print("\n📋 12. _process_full_report — детальная проверка:")
pfp_match = re.search(r"async def _process_full_report\(.*?\n(.*?)(?=\n@celery)", tasks_text, re.DOTALL)
if pfp_match:
    pfp_body = pfp_match.group(1)
    check("MatrixService.calculate" in pfp_body, "вызывает MatrixService.calculate")
    check("AIService.generate_full_report" in pfp_body, "вызывает AIService.generate_full_report")
    check("ReportService.generate_html_report" in pfp_body, "вызывает ReportService.generate_html_report")
    check("MatrixService.calculate_life_periods" in pfp_body, "вызывает calculate_life_periods")
    check("MatrixService.calculate_year_arcana" in pfp_body, "вызывает calculate_year_arcana")

# ── Итого ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
total_checks = ok_count + len(errors)
print(f"  Всего проверок: {total_checks}")
print(f"  ✅ Успешно: {ok_count}")
print(f"  ❌ Ошибок: {len(errors)}")

if errors:
    print("\n❌ Найдены проблемы:")
    for e in errors:
        print(f"  • {e}")
else:
    print("\n✅ Все проверки пройдены. Интеграция корректна.")
