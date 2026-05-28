def ask_partner_name_text() -> str:
    return (
        "❤️ Совместимость архетипов\n\n"
        "Как зовут человека, с которым хочешь проверить совместимость?\n\n"
        "<i>Введи имя — оно появится в разборе</i>"
    )


def ask_relation_type_text(partner_name: str) -> str:
    return f"Хорошо. Кем {partner_name} приходится тебе?"


def ask_partner_date_text(partner_name: str) -> str:
    return f"Введи дату рождения {partner_name} в формате ДД.ММ.ГГГГ"


def loading_steps() -> list[str]:
    return [
        "🔮 Сравниваю матрицы...",
        "🔮 Анализирую пересечения арканов...",
        "🔮 Формирую портрет пары...",
        "🔮 Почти готово...",
    ]


def mini_compatibility_text(
    user_name: str,
    partner_name: str,
    relation_type: str,
    block_emotional: str,
    block_portrait_user: str,
    block_portrait_partner: str,
) -> str:
    return (
        f"<b>✦ Совместимость архетипов</b>\n\n"
        f"<i>{user_name} + {partner_name}</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>🎭 Портрет {user_name}</b>\n{block_portrait_user}\n\n"
        f"<b>🎭 Портрет {partner_name}</b>\n{block_portrait_partner}\n\n"
        f"<b>💞 Эмоциональная совместимость</b>\n{block_emotional}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✦ Это только начало\n\n"
        "Полный разбор покажет:\n"
        "• <b>Зоны напряжения</b> — где может возникать трение\n"
        "• <b>Сильные стороны</b> — в чём вы усиливаете друг друга\n"
        "• <b>Рекомендация</b> — как выстроить взаимодействие"
    )


def compat_details_text(
    user_name: str,
    partner_name: str,
    arcana_first_number: int,
    arcana_first_name: str,
    arcana_second_number: int,
    arcana_second_name: str,
) -> str:
    return (
        "🔍 <b>Как NURA считает совместимость</b>\n\n"
        f"<b>{user_name}</b>\n"
        f"Аркан: {arcana_first_number}. {arcana_first_name}\n"
        "Это центральный аркан матрицы — архетип, который определяет "
        "базовую стратегию человека, его реакции и способ принятия решений.\n\n"
        f"<b>{partner_name}</b>\n"
        f"Аркан: {arcana_second_number}. {arcana_second_name}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Метод расчёта:</b>\n"
        "Каждая дата рождения даёт число от 1 до 22 — номер аркана Таро. "
        "Это не гороскоп: аркан описывает психологическую структуру "
        "человека — как он строит отношения, реагирует на стресс, "
        "принимает решения.\n\n"
        "Совместимость рассчитывается по трём осям:\n"
        "• <b>Энергетическое сочетание</b> — усиливают или гасят друг друга\n"
        "• <b>Зоны конфликта</b> — где архетипы противоречат\n"
        "• <b>Точки роста</b> — где разница становится силой\n\n"
        "AI анализирует пересечение всех трёх осей и формирует "
        "персональный текст для конкретной пары."
    )
