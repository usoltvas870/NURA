import ast
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SCHEMAS_INIT = ROOT / "core" / "schemas" / "__init__.py"
AI_SERVICE = ROOT / "core" / "services" / "ai.py"
MATRIX_SERVICE = ROOT / "core" / "services" / "matrix.py"
TASKS = ROOT / "core" / "tasks.py"
REPORT_SERVICE = ROOT / "core" / "services" / "report.py"
COT_PROMPT = ROOT / "core" / "prompts" / "cot_instruction.txt"
FULL_REPORT_TXT = ROOT / "core" / "prompts" / "full_report.txt"
TEMPLATES_DIR = ROOT / "frontend" / "reports" / "templates"
FULL_REPORT_HTML = TEMPLATES_DIR / "full_report.html"
STYLES_HTML = TEMPLATES_DIR / "_styles.html"

OK = 0
FAIL = 0
WARN = 0

MARK_OK = "\u2705"
MARK_FAIL = "\u274c"
MARK_WARN = "\u26a0"


def check(name: str, ok: bool, detail: str = "") -> None:
    global OK, FAIL
    if ok:
        print(f"  {MARK_OK} {name}")
        OK += 1
    else:
        print(f"  {MARK_FAIL} {name}: {detail}")
        FAIL += 1


def warn(msg: str) -> None:
    global WARN
    print(f"  {MARK_WARN}  {msg}")
    WARN += 1


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_dict_keys(source: str, dict_name: str) -> set:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == dict_name:
                    if isinstance(node.value, ast.Dict):
                        return {
                            k.value
                            for k in node.value.keys
                            if isinstance(k, ast.Constant)
                        }
    return set()


def extract_class_fields(source: str, class_name: str) -> set:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if not item.target.id.startswith("_"):
                        fields.add(item.target.id)
            return fields
    return set()


def extract_jinja_includes(source: str) -> set:
    return set(re.findall(r"""{%\s*include\s+['\"](.+?)['\"]\s*%}""", source))


def extract_css_classes(source: str) -> set:
    """Extract CSS class names from HTML, filtering Jinja artifacts.

    Strips both {% %} and {{ }} blocks before extracting class attributes.
    """
    result = set()
    cleaned = re.sub(r"{%[^%]*%}", " ", source)
    cleaned = re.sub(r"\{\{[^}]*\}\}", " ", cleaned)
    for m in re.finditer(r'class="([^"]+)"', cleaned):
        raw = m.group(1)
        for c in raw.split():
            c = c.strip()
            if should_skip_class_fragment(c):
                continue
            result.add(c)
    for m in re.finditer(r"class='([^']+)'", cleaned):
        raw = m.group(1)
        for c in raw.split():
            c = c.strip()
            if should_skip_class_fragment(c):
                continue
            result.add(c)
    return result


def should_skip_class_fragment(c: str) -> bool:
    if not c:
        return True
    if any(tok in c for tok in ("{{", "}}", "{%", "%}")):
        return True
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', c):
        return True
    if c.endswith("-"):
        return True
    return False


def extract_css_selectors(source: str) -> set:
    return set(re.findall(r"\.([a-zA-Z_][a-zA-Z0-9_-]*)", source))


def extract_kitchen_keys(source: str) -> set:
    m = re.search(r"FALLBACK_KITCHEN.*?for\s+key\s+in\s+\[(.*?)\]", source, re.DOTALL)
    if m:
        return set(re.findall(r'"([^"]+)"', m.group(1)))
    return set()


def extract_matrix_raw_keys(source: str) -> set:
    idx = source.find("async def _process_full_report(")
    if idx == -1:
        return set()
    chunk = source[idx:]
    m = re.search(r"matrix_raw\s*=\s*\{(.*?)\}", chunk, re.DOTALL)
    if not m:
        return set()
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def extract_report_data_keys(source: str) -> set:
    idx = source.find("async def _process_full_report(")
    if idx == -1:
        return set()
    chunk = source[idx:]
    m = re.search(r"generate_html_report\(\s*report_data=\{(.*?)\},", chunk, re.DOTALL)
    if not m:
        return set()
    return set(re.findall(r'"(\w+)"', m.group(1)))


def count_cot_steps(text: str) -> int:
    return len(re.findall(r"==\s*Шаг\s*\d+", text))


def count_json_schema_fields(text: str) -> int:
    return len(re.findall(r'^\s{2}"(\w+)":\s*"Минимум\s+(\d+)', text, re.MULTILINE))


def has_max_tokens_32000(source: str) -> bool:
    m = re.search(r"FULL_REPORT_PARAMS\s*=\s*\{(.*?)\}", source, re.DOTALL)
    if not m:
        return False
    return re.search(r'"max_tokens"\s*:\s*32000', m.group(1)) is not None


def check_field_validations(schemas_src: str, expected_fields: set) -> None:
    print("\n[2] FullReportResult fields have Field(min_length, max_length, description)")
    tree = ast.parse(schemas_src)
    all_ok = True
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "FullReportResult":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fname = item.target.id
                    if fname.startswith("_"):
                        continue
                    has_field = False
                    min_l = None
                    max_l = None
                    has_desc = False
                    if (
                        isinstance(item.value, ast.Call)
                        and isinstance(item.value.func, ast.Name)
                        and item.value.func.id == "Field"
                    ):
                        has_field = True
                        for kw in item.value.keywords:
                            if kw.arg == "min_length":
                                min_l = getattr(kw.value, "value", None)
                            if kw.arg == "max_length":
                                max_l = getattr(kw.value, "value", None)
                            if kw.arg == "description":
                                has_desc = True
                    field_ok = True
                    field_ok &= has_field
                    field_ok &= min_l is not None and min_l > 0
                    field_ok &= max_l is not None and max_l > 0
                    field_ok &= has_desc
                    if not field_ok:
                        all_ok = False
                        check(f"Field '{fname}'", has_field,
                              f"Field={has_field} min={min_l} max={max_l} desc={has_desc}")
            break
    if all_ok:
        check("All 15 fields have Field(min_length, max_length, description)", True)


def main():
    global OK, FAIL, WARN
    print("=" * 60)
    print("NURA Integrity Check")
    print("=" * 60)

    schemas_src = read(SCHEMAS_INIT)
    ai_src = read(AI_SERVICE)
    matrix_src = read(MATRIX_SERVICE)
    tasks_src = read(TASKS)
    report_src = read(REPORT_SERVICE)

    expected_fields = {
        "main_archetype", "strengths", "shadow_side", "relationship_dynamics",
        "financial_scenario", "recurring_mistakes", "internal_conflicts",
        "life_cycles", "ai_recommendations", "karmic_tail_analysis",
        "ancestral_programs", "life_purpose", "life_forecast",
        "psychological_blocks", "health_analysis",
    }

    # 1
    print("\n[1] FALLBACK_FULL keys == FullReportResult fields")
    full_fields = extract_class_fields(schemas_src, "FullReportResult")
    fallback_keys = extract_dict_keys(ai_src, "FALLBACK_FULL")
    check("FullReportResult has 15 fields", len(full_fields) == 15,
          f"Expected 15, got {len(full_fields)}: {sorted(full_fields)}")
    check("FALLBACK_FULL has 15 keys", len(fallback_keys) == 15,
          f"Expected 15, got {len(fallback_keys)}: {sorted(fallback_keys)}")
    check("FALLBACK_FULL == FullReportResult", fallback_keys == full_fields,
          f"Diff: {fallback_keys ^ full_fields}")
    check("Fields match spec", full_fields == expected_fields,
          f"Diff: {full_fields ^ expected_fields}")

    # 2: Field validations
    check_field_validations(schemas_src, expected_fields)

    # 3: FALLBACK_KITCHEN
    print("\n[3] FALLBACK_KITCHEN: 14 keys (all except ai_recommendations)")
    kitchen_keys = extract_kitchen_keys(ai_src)
    expected_kitchen = expected_fields - {"ai_recommendations"}
    check("FALLBACK_KITCHEN has 14 keys", len(kitchen_keys) == 14,
          f"Expected 14, got {len(kitchen_keys)}: {sorted(kitchen_keys)}")
    check("FALLBACK_KITCHEN matches expected", kitchen_keys == expected_kitchen,
          f"Extra: {kitchen_keys - expected_kitchen} | Missing: {expected_kitchen - kitchen_keys}")

    # 4: FULL_REPORT_PARAMS
    print("\n[4] FULL_REPORT_PARAMS: max_tokens = 32000")
    check("max_tokens == 32000", has_max_tokens_32000(ai_src), "Not found")

    # 5: MatrixService
    print("\n[5] MatrixService methods")
    check("calculate_year_arcana exists", "def calculate_year_arcana(" in matrix_src)
    check("calculate_life_periods exists", "def calculate_life_periods(" in matrix_src)
    check("calculate_year_forecast exists", "def calculate_year_forecast(" in matrix_src)
    check("format_for_prompt: life periods",
          "жизненные периоды" in matrix_src.lower())
    check("format_for_prompt: year forecast",
          "прогноз по годам" in matrix_src.lower())
    check("format_for_prompt: health map",
          "карта здоровья" in matrix_src.lower())

    # 6: cot_instruction.txt
    print("\n[6] cot_instruction.txt: 9 steps")
    cot_text = read(COT_PROMPT)
    n = count_cot_steps(cot_text)
    check("9 steps found", n == 9, f"Found {n}")
    check("Step 8: Психологические блоки", "Психологические блоки" in cot_text)
    check("Step 9: Карта здоровья", "Карта здоровья" in cot_text)

    # 7: full_report.txt
    print("\n[7] full_report.txt: 15 fields with 300-word requirement")
    fr_text = read(FULL_REPORT_TXT)
    n_fields = count_json_schema_fields(fr_text)
    check("15 JSON schema fields", n_fields == 15, f"Found {n_fields}")

    # 8: _process_full_report
    print("\n[8] _process_full_report: matrix_raw and report_data")
    matrix_keys = extract_matrix_raw_keys(tasks_src)
    req_matrix = {
        "center", "top", "bottom", "left", "right",
        "talent_zone", "comfort_zone", "portrait_zone",
        "karmic_tail", "sky_line", "earth_line",
        "relationship_line", "money_line", "relationship_point",
        "inner_f", "inner_g", "inner_h", "inner_i",
        "arcana_names", "chakra_map",
    }
    check("matrix_raw: exact 20 keys", matrix_keys == req_matrix,
          f"Extra: {matrix_keys - req_matrix} | Missing: {req_matrix - matrix_keys}")
    check("matrix_raw: has all 4 lines",
          {"sky_line", "earth_line", "relationship_line", "money_line"}.issubset(matrix_keys))
    check("matrix_raw: has inner points",
          {"relationship_point", "inner_f", "inner_g", "inner_h", "inner_i"}.issubset(matrix_keys))
    check("matrix_raw: has chakra_map + arcana_names",
          {"chakra_map", "arcana_names"}.issubset(matrix_keys))

    report_keys = extract_report_data_keys(tasks_src)
    expected_report = {
        "matrix", "analysis", "kitchen_analysis", "user_name",
        "archetype_name", "archetype_number", "recommendations_parsed",
        "life_periods", "year_forecast", "current_year_arcana",
        "chakra_data", "psych_blocks",
    }
    check("report_data: 12 keys", report_keys == expected_report,
          f"Extra: {report_keys - expected_report} | Missing: {expected_report - report_keys}")

    # 9: ReportService
    print("\n[9] ReportService")
    check("parse_recommendations() exists", "def parse_recommendations(" in report_src)
    check("parse_psych_blocks() exists", "def parse_psych_blocks(" in report_src)
    check("generate_html_report uses **report_data",
          "**report_data" in report_src)
    check("generate_html_report passes bot_username",
          "bot_username" in report_src)
    warn("kitchen_analysis & psych_blocks flow via **report_data from tasks.py")

    # 10: Jinja includes
    print("\n[10] full_report.html includes -> existing files")
    fr_html = read(FULL_REPORT_HTML)
    includes = extract_jinja_includes(fr_html)
    existing = {f.name for f in TEMPLATES_DIR.iterdir() if f.is_file()}
    for inc in sorted(includes):
        check(f"Include '{inc}'", inc in existing, "File not found")

    # 11: Optional templates
    print("\n[11] Optional: _nav_sidebar.html, _toc.html")
    for fname in ["_nav_sidebar.html", "_toc.html"]:
        p = TEMPLATES_DIR / fname
        if p.exists():
            check(f"{fname} exists", True)
        else:
            warn(f"{fname} missing")

    # 12: CSS classes
    print("\n[12] CSS classes: templates -> _styles.html")
    styles_css = read(STYLES_HTML)
    defined = extract_css_selectors(styles_css)

    all_template_classes = set()
    for tf in sorted(TEMPLATES_DIR.glob("*.html")):
        all_template_classes.update(extract_css_classes(read(tf)))

    section_prefixes = {c for c in all_template_classes if c.startswith("section-")}
    missing = all_template_classes - defined - section_prefixes

    if missing:
        print(f"  {MARK_FAIL} {len(missing)} missing CSS class(es):")
        for m in sorted(missing):
            print(f"       .{m}")
        FAIL += 1
    else:
        check("All CSS classes found in _styles.html", True)
    if section_prefixes:
        warn(f"{len(section_prefixes)} dynamic section-* classes (generated at runtime)")

    # 13: All required templates
    print("\n[13] Required template files")
    required = [
        "_base.html", "_cover.html", "_footer.html",
        "_matrix_full.html", "_matrix_3x3.html", "_dashboard.html",
        "_section_karmic_tail.html", "_section_ancestral.html",
        "_section_purposes.html", "_section_forecast.html",
        "_health_map.html", "_psychological_blocks.html",
        "_reflection.html", "_practices.html", "_tarot_card.html",
        "_kitchen_toggle.html", "_recommendation_day.html",
        "_line_visual.html", "_section_card.html", "_styles.html",
        "full_report.html", "compatibility_report.html", "mini_report.html",
    ]
    for tname in required:
        exists = (TEMPLATES_DIR / tname).exists()
        check(tname, exists, "Missing")

    # 14: Parse methods
    print("\n[14] ReportService parse methods extract expected data")
    rec_cats = '"Тело"' in report_src or "'Тело'" in report_src
    check("parse_recommendations: extracts category", rec_cats)
    check("parse_recommendations: extracts effect", "effect" in report_src)
    psych_keys = all(
        k in report_src for k in [
            '"arcana"', '"arcana_name"', '"belief"', '"manifestation"', '"strategy"'
        ]
    )
    check("parse_psych_blocks: returns arcana/belief/manifestation/strategy", psych_keys)

    # Summary
    print("\n" + "=" * 60)
    total = OK + FAIL
    print(f"Results: {OK}/{total} passed, {FAIL} failed, {WARN} warnings")
    if FAIL > 0:
        print(MARK_FAIL + " INTEGRITY CHECK FAILED")
    else:
        print(MARK_OK + " ALL CHECKS PASSED")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
