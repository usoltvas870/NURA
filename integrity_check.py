"""Скрипт проверки целостности интеграции таро.
Запуск без зависимостей: python integrity_check.py
"""

import ast
import importlib.util
import os
import sys
from pathlib import Path

NURA_APP = Path(__file__).parent / "nura_app"
sys.path.insert(0, str(NURA_APP))

OK = "✅ OK"
FAIL = "❌ ПРОБЛЕМА"

errors: list[str] = []


def check_file_exists(path: Path, label: str) -> None:
    if path.exists():
        print(f"  {OK} {label}: {path}")
    else:
        msg = f"Файл не найден: {path}"
        print(f"  {FAIL} {label}: {msg}")
        errors.append(msg)


def check_imports(module_path: str, label: str) -> None:
    """Проверяет что модуль импортируется (без выполнения)."""
    full_path = NURA_APP / module_path
    if not full_path.exists():
        print(f"  {FAIL} {label}: файл не найден {full_path}")
        errors.append(f"Импорт {label}: файл не найден")
        return
    try:
        source = full_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        print(f"  {OK} {label}: синтаксис OK, {len(imports)} импортов")
    except SyntaxError as e:
        print(f"  {FAIL} {label}: SyntaxError {e}")
        errors.append(f"Синтаксис {label}: {e}")


def check_callback_unique(file_paths: list[str]) -> None:
    """Проверяет что все tarot-specific callback_data уникальны."""
    all_callbacks: dict[str, list[str]] = {}
    for fp in file_paths:
        path = Path(fp) if os.path.isabs(fp) else NURA_APP / fp
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in getattr(node, "keywords", []):
                    if kw.arg == "callback_data" and isinstance(kw.value, ast.Constant):
                        val = kw.value.value
                        if val not in all_callbacks:
                            all_callbacks[val] = []
                        all_callbacks[val].append(str(path))

    target = ["tarot_daily_card", "tarot_weekly_spread", "tarot_ask_question", "tarot_menu"]

    print(f"\n[CALLBACK DATA]")
    print(f"  Найдено уникальных callback_data: {len(all_callbacks)}")

    # Check target callbacks are present
    found_targets = [t for t in target if t in all_callbacks]
    missing = [t for t in target if t not in all_callbacks]
    if found_targets:
        print(f"  {OK} Целевые callback'и найдены: {found_targets}")
    if missing:
        print(f"  {FAIL} Не найдены: {missing}")
        errors.append(f"Callback'и не найдены: {missing}")

    # Only flag duplicates for tarot-specific callbacks that appear in >2 files
    # (tarot_menu in 2 files is intentional: main_menu button + tarot back button)
    tarot_duplicates = {
        k: v for k, v in all_callbacks.items()
        if k.startswith("tarot_") and len(set(v)) > 2
    }
    if tarot_duplicates:
        print(f"  {FAIL} Дубликаты tarot-callback'ов: {tarot_duplicates}")
        errors.append(f"Дубликаты tarot-callback_data: {tarot_duplicates}")
    else:
        print(f"  {OK} Tarot-callback'и уникальны")


def check_model_fields(file_path: Path, class_name: str, required_fields: list[str]) -> None:
    """Проверяет наличие полей в SQLAlchemy модели."""
    if not file_path.exists():
        print(f"  {FAIL} Файл не найден: {file_path}")
        errors.append(f"Модель {class_name}: файл не найден")
        return
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields_in_class = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields_in_class.add(item.target.id)
            missing = [f for f in required_fields if f not in fields_in_class]
            if missing:
                print(f"  {FAIL} {class_name}: отсутствуют поля {missing}")
                errors.append(f"Модель {class_name}: нет полей {missing}")
            else:
                print(f"  {OK} {class_name}: все поля на месте ({required_fields})")
            return
    print(f"  {FAIL} Класс {class_name} не найден в {file_path}")
    errors.append(f"Класс {class_name} не найден")


def check_prompt_fields(prompt_path: Path, required_tokens: list[str]) -> None:
    """Проверяет что промпт содержит все необходимые placeholders."""
    if not prompt_path.exists():
        print(f"  {FAIL} Промпт не найден: {prompt_path}")
        errors.append(f"Промпт: {prompt_path.name} не найден")
        return
    content = prompt_path.read_text(encoding="utf-8")
    missing = [t for t in required_tokens if t not in content]
    if missing:
        print(f"  {FAIL} {prompt_path.name}: нет токенов {missing}")
        errors.append(f"Промпт {prompt_path.name}: нет {missing}")
    else:
        print(f"  {OK} {prompt_path.name}: все токены на месте")


def check_router_registered(bot_main: Path) -> None:
    """Проверяет что tarot_router зарегистрирован в dp.include_router."""
    if not bot_main.exists():
        print(f"  {FAIL} bot/main.py не найден")
        errors.append("bot/main.py не найден")
        return
    content = bot_main.read_text(encoding="utf-8")
    if "tarot_router" in content and "include_router" in content:
        print(f"  {OK} tarot_router зарегистрирован в bot/main.py")
    else:
        print(f"  {FAIL} tarot_router НЕ найден в bot/main.py")
        errors.append("tarot_router не зарегистрирован")


def check_payment_route_logic(file_path: Path) -> None:
    """Проверяет логику payment webhook."""
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    checks = [
        ("payment_type == \"tarot\"", "обработка tarot"),
        ("update_tarot_subscription", "вызов update_tarot_subscription"),
        ("payment_type == \"matrix\"", "обработка matrix"),
        ("update_has_matrix", "вызов update_has_matrix"),
    ]
    for token, desc in checks:
        if token in content:
            print(f"  {OK} payment.py: {desc}")
        else:
            print(f"  {FAIL} payment.py: {desc} отсутствует")
            errors.append(f"payment.py: {desc}")


def check_payment_service(file_path: Path) -> None:
    """Проверяет create_tarot_payment и create_matrix_payment."""
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    checks = [
        ("create_tarot_payment", "метод create_tarot_payment"),
        ('"payment_type": "tarot"', 'metadata.payment_type = "tarot"'),
        ("create_matrix_payment", "метод create_matrix_payment"),
        ('"payment_type": "matrix"', 'metadata.payment_type = "matrix"'),
        ("create_subscription", "метод create_subscription"),
    ]
    for token, desc in checks:
        if token in content:
            print(f"  {OK} payment_service: {desc}")
        else:
            print(f"  {FAIL} payment_service: {desc} отсутствует")
            errors.append(f"payment_service: {desc}")


def check_daily_arcana(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    for func in ["calculate_daily_arcana", "calculate_spread_arcanas", "get_today_arcana_with_name"]:
        if f"def {func}" in content:
            print(f"  {OK} daily_arcana: {func}")
        else:
            print(f"  {FAIL} daily_arcana: {func} отсутствует")
            errors.append(f"daily_arcana: {func}")


def check_ai_service(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    for func in [
        "generate_tarot_daily_card",
        "generate_tarot_weekly_spread",
        "generate_tarot_question",
        "_get_matrix_context",
    ]:
        if f"def {func}" in content:
            print(f"  {OK} ai.py: {func}")
        else:
            print(f"  {FAIL} ai.py: {func} отсутствует")
            errors.append(f"ai.py: {func}")


def check_tasks(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    for item in ["send_daily_tarot_card", "format_daily_card_message", "send_daily_card"]:
        if item in content:
            print(f"  {OK} tasks.py: {item}")
        else:
            print(f"  {FAIL} tasks.py: {item} отсутствует")
            errors.append(f"tasks.py: {item}")


def check_handlers(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    handlers = [
        "cmd_ritual",
        "show_tarot_menu",
        "show_tarot_daily_card",
        "show_tarot_weekly_spread",
        "ask_tarot_question",
        "handle_tarot_question",
    ]
    for h in handlers:
        if f"def {h}" in content or f"async def {h}" in content:
            print(f"  {OK} tarot.py: {h}")
        else:
            print(f"  {FAIL} tarot.py: {h} отсутствует")
            errors.append(f"tarot.py: {h}")

    if "_check_tarot_subscription" in content:
        print(f"  {OK} tarot.py: проверка подписки _check_tarot_subscription")
    else:
        print(f"  {FAIL} tarot.py: _check_tarot_subscription отсутствует")
        errors.append("tarot.py: _check_tarot_subscription")


def check_keyboards(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    kb_funcs = ["tarot_menu_keyboard", "tarot_back_keyboard"]
    for kf in kb_funcs:
        if f"def {kf}" in content:
            print(f"  {OK} tarot_keyboard.py: {kf}")
        else:
            print(f"  {FAIL} tarot_keyboard.py: {kf} отсутствует")
            errors.append(f"tarot_keyboard: {kf}")


def check_main_menu(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    has_tarot_param = "has_tarot" in content
    has_tarot_menu_cb = '"tarot_menu"' in content or "'tarot_menu'" in content
    if has_tarot_param and has_tarot_menu_cb:
        print(f"  {OK} main_menu.py: has_tarot + tarot_menu кнопка")
    else:
        missing_parts = []
        if not has_tarot_param:
            missing_parts.append("has_tarot")
        if not has_tarot_menu_cb:
            missing_parts.append("tarot_menu")
        print(f"  {FAIL} main_menu.py: отсутствуют: {missing_parts}")
        errors.append(f"main_menu.py: {missing_parts}")


def check_tarot_template(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    if "daily_tarot_arcana" in content:
        print(f"  {OK} _tarot_card.html: daily_tarot_arcana (а не current_year_arcana)")
    else:
        print(f"  {FAIL} _tarot_card.html: daily_tarot_arcana не найден")
        errors.append("_tarot_card.html: daily_tarot_arcana")


def check_index_html(file_path: Path) -> None:
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    checks = [
        ("#tarot-preview", "блок #tarot-preview"),
        ("#benefits", "блок #benefits"),
        ("#pricing", "блок #pricing"),
        ("#faq", "блок #faq"),
        ("Таро-подписка", "3-й продукт Таро-подписка в #pricing"),
        ("Ежедневная карта Таро", "+1 карточка в #benefits"),
        ("Чем таро-ритуалы отличаются", "FAQ: таро-вопрос 1"),
        ("Нужна ли полная матрица для ритуалов", "FAQ: таро-вопрос 2"),
        ("Попробовать карту дня", "CTA: вторая кнопка"),
    ]
    for token, desc in checks:
        if token in content:
            print(f"  {OK} index.html: {desc}")
        else:
            print(f"  {FAIL} index.html: {desc} — не найден '{token}'")
            errors.append(f"index.html: {desc}")


def main() -> None:
    print("=" * 60)
    print("INTEGRITY CHECK — NURA TAROT INTEGRATION")
    print("=" * 60)

    # 1. Файлы существуют
    print("\n[1] ПРОВЕРКА СУЩЕСТВОВАНИЯ ФАЙЛОВ")
    files = [
        ("core/models.py", "User/Payment модели"),
        ("core/services/payment.py", "Payment service"),
        ("core/services/daily_arcana.py", "Daily arcana service"),
        ("core/services/ai.py", "AI service"),
        ("core/tasks.py", "Celery tasks"),
        ("api/routes/payment.py", "Payment routes"),
        ("bot/handlers/tarot.py", "Tarot handlers"),
        ("bot/keyboards/main_menu.py", "Main menu keyboard"),
        ("bot/keyboards/tarot_keyboard.py", "Tarot keyboard"),
        ("bot/states/tarot_state.py", "Tarot states"),
        ("bot/helpers/tarot_formatter.py", "Tarot formatter"),
        ("bot/main.py", "Bot main"),
        ("core/prompts/tarot_daily_card.txt", "Prompt: daily card"),
        ("core/prompts/tarot_weekly_spread.txt", "Prompt: weekly spread"),
        ("core/prompts/tarot_question.txt", "Prompt: question"),
        ("frontend/reports/templates/_tarot_card.html", "Tarot card template"),
        ("core/repositories/user.py", "User repository"),
        ("core/schemas/__init__.py", "Schemas"),
    ]
    for rel_path, label in files:
        check_file_exists(NURA_APP / rel_path, label)
    check_file_exists(Path(__file__).parent / "index.html", "Landing index.html")

    # 2. Импорты в новых файлах
    print("\n[2] ПРОВЕРКА СИНТАКСИСА НОВЫХ ФАЙЛОВ")
    new_files = [
        "bot/handlers/tarot.py",
        "bot/keyboards/tarot_keyboard.py",
        "bot/states/tarot_state.py",
        "bot/helpers/tarot_formatter.py",
        "core/services/daily_arcana.py",
    ]
    for fp in new_files:
        check_imports(fp, fp)

    # 3. Callback уникальность
    print("\n[3] ПРОВЕРКА CALLBACK_DATA")
    callback_files = [
        str(NURA_APP / "bot/handlers/tarot.py"),
        str(NURA_APP / "bot/keyboards/tarot_keyboard.py"),
        str(NURA_APP / "bot/keyboards/main_menu.py"),
    ]
    check_callback_unique(callback_files)

    # 4. Модели
    print("\n[4] ПРОВЕРКА МОДЕЛЕЙ")
    check_model_fields(NURA_APP / "core/models.py", "User", ["tarot_subscription", "tarot_subscription_until"])
    check_model_fields(NURA_APP / "core/models.py", "Payment", ["payment_type"])

    # 5. Payment service
    print("\n[5] ПРОВЕРКА PAYMENT SERVICE")
    check_payment_service(NURA_APP / "core/services/payment.py")

    # 6. Payment routes
    print("\n[6] ПРОВЕРКА PAYMENT ROUTES")
    check_payment_route_logic(NURA_APP / "api/routes/payment.py")

    # 7. Daily arcana
    print("\n[7] ПРОВЕРКА DAILY ARCANA")
    check_daily_arcana(NURA_APP / "core/services/daily_arcana.py")

    # 8. AI service
    print("\n[8] ПРОВЕРКА AI SERVICE")
    check_ai_service(NURA_APP / "core/services/ai.py")

    # 9. Tasks
    print("\n[9] ПРОВЕРКА TASKS")
    check_tasks(NURA_APP / "core/tasks.py")

    # 10. Handlers
    print("\n[10] ПРОВЕРКА HANDLERS")
    check_handlers(NURA_APP / "bot/handlers/tarot.py")

    # 11. Keyboards
    print("\n[11] ПРОВЕРКА KEYBOARDS")
    check_keyboards(NURA_APP / "bot/keyboards/tarot_keyboard.py")
    check_main_menu(NURA_APP / "bot/keyboards/main_menu.py")

    # 12. Prompts (nura_app)
    print("\n[12] ПРОВЕРКА ПРОМПТОВ (nura_app)")
    check_prompt_fields(NURA_APP / "core/prompts/tarot_daily_card.txt", ["{user_name}", "{birth_date}", "{daily_arcana}", "{matrix_context}"])
    check_prompt_fields(NURA_APP / "core/prompts/tarot_weekly_spread.txt", ["{user_name}", "{birth_date}", "{three_arcana}", "{matrix_context}"])
    check_prompt_fields(NURA_APP / "core/prompts/tarot_question.txt", ["{user_name}", "{birth_date}", "{question}", "{three_arcana}", "{matrix_context}"])

    # 13. Schema models
    print("\n[13] ПРОВЕРКА СХЕМ")
    schemas_path = NURA_APP / "core/schemas/__init__.py"
    if schemas_path.exists():
        content = schemas_path.read_text(encoding="utf-8")
        for cls_name in ["TarotDailyCardResult", "TarotWeeklySpreadResult", "TarotQuestionResult"]:
            if f"class {cls_name}" in content:
                print(f"  {OK} schemas: {cls_name}")
            else:
                print(f"  {FAIL} schemas: {cls_name} отсутствует")
                errors.append(f"schemas: {cls_name}")

    # 14. Router registration
    print("\n[14] ПРОВЕРКА РЕГИСТРАЦИИ РОУТЕРА")
    check_router_registered(NURA_APP / "bot/main.py")

    # 15. Template
    print("\n[15] ПРОВЕРКА HTML ШАБЛОНА")
    check_tarot_template(NURA_APP / "frontend/reports/templates/_tarot_card.html")

    # 16. Landing index.html
    print("\n[16] ПРОВЕРКА ЛЕНДИНГА (index.html)")
    check_index_html(Path(__file__).parent / "index.html")

    # 17. Formatter
    print("\n[17] ПРОВЕРКА FORMATTER")
    formatter = NURA_APP / "bot/helpers/tarot_formatter.py"
    if formatter.exists():
        content = formatter.read_text(encoding="utf-8")
        for func in ["format_tarot_message", "format_tarot_paywall"]:
            if f"def {func}" in content:
                print(f"  {OK} tarot_formatter.py: {func}")
            else:
                print(f"  {FAIL} tarot_formatter.py: {func} отсутствует")
                errors.append(f"tarot_formatter: {func}")

    # 18. Tarot state
    print("\n[18] ПРОВЕРКА TAROT STATE")
    state_file = NURA_APP / "bot/states/tarot_state.py"
    if state_file.exists():
        content = state_file.read_text(encoding="utf-8")
        if "TarotStates" in content and "waiting_question" in content:
            print(f"  {OK} tarot_state.py: TarotStates.waiting_question")
        else:
            print(f"  {FAIL} tarot_state.py: TarotStates не найден")
            errors.append("tarot_state: TarotStates")

    # ИТОГ
    print("\n" + "=" * 60)
    if errors:
        print(f"{FAIL}: найдено проблем: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"{OK}: все проверки пройдены успешно!")
        print("Интеграция таро целостна.")
        sys.exit(0)


if __name__ == "__main__":
    main()
