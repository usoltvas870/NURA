def explanation_text() -> str:
    return (
        "<b>❤️ Совместимость архетипов</b>\n\n"
        "У каждого архетипа есть своя <i>«частота»</i>.\n"
        "Одни сочетания дают мощный поток энергии.\n"
        "Другие — создают напряжённость, которая может\n"
        "стать как точкой роста, так и источником боли.\n\n"
        "<b>Я покажу:</b>\n"
        "• Как сочетаются ваши архетипы\n"
        "• Где возникают зоны конфликтов\n"
        "• Какие сильные стороны у вашей пары\n\n"
        "<i>Введи дату рождения человека, с которым хочешь проверить совместимость, в формате ДД.ММ.ГГГГ</i>"
    )


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
    portrait_user: str,
    portrait_partner: str,
    how_you_interact: str,
    relation_type: str = "общение",
) -> str:
    rel_labels = {
        "романтика":  "В паре",
        "дружба":     "В дружбе",
        "работа":     "В команде",
        "семья":      "В семье",
        "общение":    "Как вы взаимодействуете",
    }
    interact_label = rel_labels.get(relation_type, "Как вы взаимодействуете")

    return (
        f"<b>✦ Совместимость</b>\n\n"
        f"<b>🎭 {user_name}</b>\n"
        f"{portrait_user}\n\n"
        f"<b>🎭 {partner_name}</b>\n"
        f"{portrait_partner}\n\n"
        f"<b>💞 {interact_label}</b>\n"
        f"{how_you_interact}"
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
