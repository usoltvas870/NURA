def ask_birth_date_text() -> str:
    return (
        "Для расчёта матрицы мне нужна твоя дата рождения.\n\n"
        "Введи её в формате ДД.ММ.ГГГГ\n\n"
        "Например: 15.06.1998\n\n"
        "Это займёт меньше минуты ✶"
    )


def invalid_format_text() -> str:
    return (
        "Формат должен быть таким: ДД.ММ.ГГГГ\n\n"
        "Попробуй ещё раз ↻\n"
        "Например: 15.06.1998"
    )


def impossible_date_text() -> str:
    return (
        "Хм, такой даты не существует.\n\n"
        "Проверь число и месяц и попробуй ещё раз ↻"
    )


def loading_step_1() -> str:
    return "✶ Считаю твою матрицу...\n\nРасшифровываю 22 аркана из чисел твоего рождения"


def loading_step_2() -> str:
    return "◈ Анализирую архетипы...\n\nСопоставляю энергии с твоими личными сценариями"


def loading_step_3() -> str:
    return "☯ Синхронизирую с энергиями...\n\nСобираю целостную картину твоей матрицы"


def loading_step_4() -> str:
    return "✦ Готово!\n\nТвоя матрица расшифрована. Смотри результат ↓"


def loading_steps() -> list[str]:
    return [loading_step_1(), loading_step_2(), loading_step_3(), loading_step_4()]


def mini_analysis_text(
    archetype_name: str,
    archetype_number: int,
    main_archetype: str,
    core_strength: str,
    emotional_conflict: str,
    relationship_pattern: str,
    financial_block: str,
) -> str:
    return (
        f"✦ Твоя Матрица Судьбы\n"
        f"Архетип: {archetype_name} | Энергия: {archetype_number}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎭 Главный архетип\n{main_archetype}\n\n"
        f"💪 Сильная сторона\n{core_strength}\n\n"
        f"🌊 Эмоциональный конфликт\n{emotional_conflict}\n\n"
        f"🔄 Паттерн отношений\n{relationship_pattern}\n\n"
        f"💰 Денежный блок\n{financial_block}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Хочешь глубже?\n"
        "В полном AI-отчёте тебя ждут:\n"
        "• Теневые стороны — то, что ты не видишь в себе\n"
        "• Жизненные циклы — периоды силы и спада\n"
        "• Совместимость — как твой архетип сочетается с другими\n"
        "• 7-дневные рекомендации под твой архетип\n\n"
        "Полный разбор: 590 ₽"
    )
