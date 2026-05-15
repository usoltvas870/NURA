def ask_birth_date_text() -> str:
    return (
        "<b>Для расчёта матрицы мне нужна твоя дата рождения.</b>\n\n"
        "Введи её в формате <b>ДД.ММ.ГГГГ</b>\n\n"
        "<i>Например: 15.06.1998</i>\n\n"
        "Это займёт меньше минуты ✶"
    )


def invalid_format_text() -> str:
    return (
        "Формат должен быть таким: <b>ДД.ММ.ГГГГ</b>\n\n"
        "Попробуй ещё раз ↻\n"
        "<i>Например: 15.06.1998</i>"
    )


def impossible_date_text() -> str:
    return (
        "Хм, такой даты не существует.\n\n"
        "<i>Проверь число и месяц и попробуй ещё раз ↻</i>"
    )


def loading_step_1() -> str:
    return "<b>✶ Считаю твою матрицу...</b>\n\nРасшифровываю 22 аркана из чисел твоего рождения"


def loading_step_2() -> str:
    return "<b>◈ Анализирую архетипы...</b>\n\nСопоставляю энергии с твоими личными сценариями"


def loading_step_3() -> str:
    return "<b>☯ Синхронизирую с энергиями...</b>\n\nСобираю целостную картину твоей матрицы"


def loading_step_4() -> str:
    return "<b>✦ Готово!</b>\n\nТвоя матрица расшифрована. Смотри результат ↓"


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
        f"<b>✦ Твоя Матрица Судьбы</b>\n"
        f"<i>Архетип: {archetype_name} | Энергия: {archetype_number}</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>🎭 Главный архетип</b>\n{main_archetype}\n\n"
        f"<b>💪 Сильная сторона</b>\n{core_strength}\n\n"
        f"<b>🌊 Эмоциональный конфликт</b>\n{emotional_conflict}\n\n"
        f"<b>🔄 Паттерн отношений</b>\n{relationship_pattern}\n\n"
        f"<b>💰 Денежный блок</b>\n{financial_block}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Хочешь глубже?</b>\n"
        "В полном AI-отчёте тебя ждут:\n"
        "• Теневые стороны — то, что ты не видишь в себе\n"
        "• Жизненные циклы — периоды силы и спада\n"
        "• Совместимость — как твой архетип сочетается с другими\n"
        "• 7-дневные рекомендации под твой архетип\n\n"
        "Полный разбор: 690 ₽"
    )
